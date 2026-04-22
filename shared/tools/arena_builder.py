"""
tools/arena_builder.py
-----------------------
Arena Builder — standalone PyGame tool for designing arenas.

Controls:
  LEFT PANEL — tabbed configuration:
    [Arena]   — width, height, wall thickness
    [Lights]  — click canvas to place, click existing to select/delete
    [Walls]   — click+drag to draw internal wall segments
    [Robot]   — click canvas to set start position, scroll to set heading

  CANVAS — live top-down preview, updates as you edit

  BOTTOM BAR:
    [New]     — reset to defaults
    [Open]    — load arena.json
    [Save]    — save arena.json
    [Launch]  — save then launch main.py as subprocess

Run:  py -3.12 tools/arena_builder.py
      py -3.12 tools/arena_builder.py --arena path/to/arena.json
"""

import json
import math
import os
import subprocess
import sys
import time

# Allow running from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

# ─── Colour palette — CRT phosphor theme ─────────────────────────────────────
# ── Locate robosim package for theme imports ─────────────────────────────────
# The arena builder is shared infrastructure. It searches for the robosim
# package in common sibling locations relative to this file's project root.
import sys as _sys
_here        = os.path.dirname(os.path.abspath(__file__))   # shared/tools/
_shared_root = os.path.dirname(_here)                       # shared/
_project_root = os.path.dirname(_shared_root)               # CloseTheGap/
for _candidate in [
    os.path.join(_project_root, "robosim"),
    os.path.join(_project_root, "robosim_extracted", "robosim"),
    os.path.join(_here, "..", "..", "robosim"),
]:
    if os.path.exists(os.path.join(_candidate, "robosim", "theme.py")):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break

from robosim.theme import (
    BG          as C_BG,
    PANEL       as C_PANEL,
    BORDER      as C_PANEL_EDGE,
    FLOOR       as C_FLOOR,
    WALL_COLOR  as C_WALL,
    LIGHT_COLOR as C_LIGHT_RING,
    WHITE_GREEN as C_HEADING,
    PHOSPHOR    as C_ACCENT,
    PHOSPHOR    as C_OK,
    PHOSPHOR_MID as C_BTN_ACT,
    PANEL_DEEP  as C_BTN,
    PHOSPHOR_DIM as C_BTN_HOV,
    AMBER       as C_SEL,
    AMBER       as C_ERR,
    TEXT        as C_TEXT,
    TEXT_DIM    as C_TEXT_DIM,
    BLUE_PH     as C_ROBOT,
    WHITE_GREEN as C_ROBOT_HDG,
)
C_ARENA_BG   = C_BG
C_WALL_INT   = C_WALL
C_LIGHT_FILL = (*C_LIGHT_RING, 60)

PANEL_W       = 340
BOTTOM_H      = 52
MARGIN        = 32
ROBOT_RADIUS  = 0.084   # metres

# ─── Default arena ───────────────────────────────────────────────────────────
DEFAULT_ARENA = {
    "width":           2.0,
    "height":          4.0,
    "wall_thickness":  0.05,
    "light_sources":   [],
    "internal_walls":  [],
    "robot_start":     {"x": 0.0, "y": 0.0, "heading_deg": 90.0},
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_arena(path):
    with open(path) as f:
        data = json.load(f)
    arena = dict(DEFAULT_ARENA)
    arena.update(data)
    if "robot_start" not in arena:
        arena["robot_start"] = {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
    if "internal_walls" not in arena:
        arena["internal_walls"] = []
    return arena


def save_arena(arena, path):
    # Strip builder-only keys not needed by simulation
    out = {k: v for k, v in arena.items()}
    with open(path, "w") as f:
        json.dump(out, f, indent=4)


# ─── Main application ─────────────────────────────────────────────────────────

class ArenaBuilder:

    TABS = ["Arena", "Lights", "Walls", "Robot"]

    def __init__(self, arena_path="arena.json"):
        self.arena_path = os.path.abspath(arena_path)
        self.arena = load_arena(self.arena_path) if os.path.exists(self.arena_path) \
                     else dict(DEFAULT_ARENA)
        self._dirty      = False
        self._status     = "Ready"
        self._status_col = C_TEXT_DIM
        self._status_t   = 0.0

        self._tab        = 0       # active tab index
        self._sel_light  = -1      # selected light index
        self._sel_wall   = -1      # selected wall index
        self._drag_wall  = None    # (x0,y0) world start of wall being drawn
        self._hover_btn  = None

        # Input field state
        self._fields = {}          # name → {"rect", "value", "focus", "error"}
        self._focused_field = None

        pygame.init()
        info = pygame.display.Info()
        self._sw = info.current_w
        self._sh = info.current_h

        # Window: leave 60px for OS chrome
        ww = min(1400, self._sw - 40)
        wh = min(900,  self._sh - 80)
        self._screen = pygame.display.set_mode((ww, wh), pygame.RESIZABLE)
        pygame.display.set_caption("RoboSim — Arena Builder")

        from robosim.theme import font_hd, font_md, font_sm
        self._font_ui   = font_md()
        self._font_sm   = font_sm()
        self._font_hd   = font_hd()
        self._font_btn  = font_md()

        self._clock = pygame.time.Clock()

    # ── Layout helpers ────────────────────────────────────────────────────────

    @property
    def _ww(self): return self._screen.get_width()
    @property
    def _wh(self): return self._screen.get_height()

    @property
    def _canvas_rect(self):
        return pygame.Rect(
            PANEL_W, 0,
            self._ww - PANEL_W,
            self._wh - BOTTOM_H
        )

    def _world_to_screen(self, wx, wy):
        """Convert world metres to canvas pixels."""
        cr  = self._canvas_rect
        aw  = self.arena["width"]
        ah  = self.arena["height"]
        scl = min((cr.width  - MARGIN*2) / aw,
                  (cr.height - MARGIN*2) / ah)
        cx  = cr.left + cr.width  // 2
        cy  = cr.top  + cr.height // 2
        return (int(cx + wx * scl),
                int(cy - wy * scl))

    def _screen_to_world(self, sx, sy):
        cr  = self._canvas_rect
        aw  = self.arena["width"]
        ah  = self.arena["height"]
        scl = min((cr.width  - MARGIN*2) / aw,
                  (cr.height - MARGIN*2) / ah)
        cx  = cr.left + cr.width  // 2
        cy  = cr.top  + cr.height // 2
        return ((sx - cx) / scl,
                (cy - sy) / scl)

    def _scale(self):
        cr = self._canvas_rect
        aw = self.arena["width"]
        ah = self.arena["height"]
        return min((cr.width  - MARGIN*2) / aw,
                   (cr.height - MARGIN*2) / ah)

    # ── Field management ──────────────────────────────────────────────────────

    def _setup_fields(self):
        self._fields = {}
        self._focused_field = None

    def _make_field(self, name, x, y, w, value):
        h = 28
        r = pygame.Rect(x, y, w, h)
        if name not in self._fields:
            # First time — create with arena value
            self._fields[name] = {
                "rect":  r,
                "value": str(value),
                "focus": name == self._focused_field,
                "error": False,
            }
        else:
            # Already exists — update rect position (layout may shift)
            # but only update value if this field is NOT focused
            self._fields[name]["rect"]  = r
            self._fields[name]["focus"] = (name == self._focused_field)
            if name != self._focused_field:
                self._fields[name]["value"] = str(value)

    def _draw_field(self, surf, name, label=None, label_w=120):
        f = self._fields.get(name)
        if not f: return
        rx, ry = f["rect"].x, f["rect"].y
        if label:
            lt = self._font_ui.render(label, True, C_TEXT_DIM)
            surf.blit(lt, (rx - label_w, ry + 6))
        col_bg  = (50, 56, 80) if f["focus"] else (35, 40, 58)
        col_brd = C_ACCENT if f["focus"] else (C_ERR if f["error"] else C_PANEL_EDGE)
        pygame.draw.rect(surf, col_bg,  f["rect"], border_radius=4)
        pygame.draw.rect(surf, col_brd, f["rect"], 1, border_radius=4)
        vt = self._font_ui.render(f["value"], True, C_TEXT)
        surf.blit(vt, (f["rect"].x + 6, f["rect"].y + 6))

    def _field_val(self, name, default=0.0):
        f = self._fields.get(name)
        if not f: return default
        try:
            return float(f["value"])
        except ValueError:
            return default

    # ── Status bar ────────────────────────────────────────────────────────────

    def _set_status(self, msg, ok=True):
        self._status     = msg
        self._status_col = C_OK if ok else C_ERR
        self._status_t   = time.monotonic()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_canvas(self, surf):
        from robosim.theme import draw_scanlines, PHOSPHOR, PHOSPHOR_DIM
        cr  = self._canvas_rect
        scl = self._scale()
        aw  = self.arena["width"]
        ah  = self.arena["height"]

        # Background
        pygame.draw.rect(surf, C_BG, cr)

        # Arena floor
        tl = self._world_to_screen(-aw/2, ah/2)
        br = self._world_to_screen( aw/2, -ah/2)
        floor_r = pygame.Rect(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1])
        pygame.draw.rect(surf, C_FLOOR, floor_r)

        # Light sources — amber gradient fill + ring
        for i, ls in enumerate(self.arena["light_sources"]):
            cx, cy = self._world_to_screen(ls["x"], ls["y"])
            r_px   = int(ls["radius"] * scl)
            for ring in range(max(1, r_px), 0, -max(1, r_px//10)):
                alpha = int(70 * (1.0 - ring/r_px))
                s = pygame.Surface((ring*2, ring*2), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 180, 0, alpha), (ring, ring), ring)
                surf.blit(s, (cx - ring, cy - ring))
            sel_col = C_SEL if i == self._sel_light else C_LIGHT_RING
            pygame.draw.circle(surf, sel_col, (cx, cy), r_px, 2)
            pygame.draw.circle(surf, sel_col, (cx, cy), 4)
            lt = self._font_sm.render(f"L{i}", True, sel_col)
            surf.blit(lt, (cx + 6, cy - 10))

        # Internal walls — phosphor green with glow
        for i, w in enumerate(self.arena["internal_walls"]):
            x0, y0 = self._world_to_screen(w["x0"], w["y0"])
            x1, y1 = self._world_to_screen(w["x1"], w["y1"])
            col   = C_SEL if i == self._sel_wall else C_WALL
            thick = max(2, int(w.get("thickness", 0.05) * scl))
            gs = pygame.Surface((cr.width, cr.height), pygame.SRCALPHA)
            pygame.draw.line(gs, (*col, 50), (x0-cr.left, y0), (x1-cr.left, y1), thick+4)
            surf.blit(gs, (cr.left, 0))
            pygame.draw.line(surf, col, (x0, y0), (x1, y1), thick)

        # Wall drag preview
        if self._drag_wall and self._tab == 2:
            mx, my = pygame.mouse.get_pos()
            if cr.collidepoint(mx, my):
                x0, y0 = self._world_to_screen(*self._drag_wall)
                pygame.draw.line(surf, C_ACCENT, (x0, y0), (mx, my), 2)

        # Arena boundary walls — bright phosphor with glow
        wt = int(self.arena["wall_thickness"] * scl)
        for pts in [
            ((-aw/2, ah/2),  (aw/2,  ah/2)),
            ((-aw/2, -ah/2), (aw/2, -ah/2)),
            ((aw/2,  -ah/2), (aw/2,  ah/2)),
            ((-aw/2, -ah/2), (-aw/2, ah/2)),
        ]:
            p0 = self._world_to_screen(*pts[0])
            p1 = self._world_to_screen(*pts[1])
            gs = pygame.Surface((cr.width, cr.height), pygame.SRCALPHA)
            pygame.draw.line(gs, (*PHOSPHOR, 35),
                             (p0[0]-cr.left, p0[1]),
                             (p1[0]-cr.left, p1[1]), max(2,wt)+6)
            surf.blit(gs, (cr.left, 0))
            pygame.draw.line(surf, C_WALL, p0, p1, max(2, wt))

        # Robot start pose
        rs  = self.arena["robot_start"]
        rcx, rcy = self._world_to_screen(rs["x"], rs["y"])
        r_px = max(4, int(ROBOT_RADIUS * scl))
        col  = C_SEL if self._tab == 3 else C_ROBOT
        # Glow
        gs = pygame.Surface((cr.width, cr.height), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*col, 50), (rcx-cr.left, rcy), r_px+5)
        surf.blit(gs, (cr.left, 0))
        pygame.draw.circle(surf, col, (rcx, rcy), r_px, 2)
        h_rad = math.radians(rs["heading_deg"])
        hx = rcx + int(math.cos(h_rad) * r_px * 1.5)
        hy = rcy - int(math.sin(h_rad) * r_px * 1.5)
        pygame.draw.line(surf, C_ROBOT_HDG, (rcx, rcy), (hx, hy), 2)

        # Dimension labels
        mid_n = self._world_to_screen(0, ah/2)
        mid_e = self._world_to_screen(aw/2, 0)
        wt_  = self._font_sm.render(f"{aw:.2f}m", True, C_TEXT_DIM)
        ht_  = self._font_sm.render(f"{ah:.2f}m", True, C_TEXT_DIM)
        surf.blit(wt_, (mid_n[0] - wt_.get_width()//2, mid_n[1] - 20))
        surf.blit(ht_, (mid_e[0] + 6, mid_e[1] - ht_.get_height()//2))

        # Tab hint overlay
        hints = {
            1: "Click to place light  |  Click existing to select  |  Del to remove",
            2: "Click+drag to draw wall  |  Click existing to select  |  Del to remove",
            3: "Click to set start position  |  Scroll to rotate heading",
        }
        if self._tab in hints:
            ht = self._font_sm.render(hints[self._tab], True, C_TEXT_DIM)
            surf.blit(ht, (cr.left + 8, cr.bottom - 22))

        # CRT scanlines
        draw_scanlines(surf, cr, alpha=20)

    def _draw_panel(self, surf):
        panel_r = pygame.Rect(0, 0, PANEL_W, self._wh - BOTTOM_H)
        pygame.draw.rect(surf, C_PANEL, panel_r)
        pygame.draw.line(surf, C_PANEL_EDGE, (PANEL_W-1, 0), (PANEL_W-1, self._wh-BOTTOM_H), 1)

        # Title
        from robosim.theme import draw_double_rule, draw_btn
        title = self._font_hd.render("ARENA BUILDER", True, C_HEADING)
        surf.blit(title, (16, 14))
        draw_double_rule(surf, 8, 46, PANEL_W - 8)

        # Tabs
        tab_y = 54
        tab_w = (PANEL_W - 16) // len(self.TABS)
        self._tab_rects = []
        mx, my = pygame.mouse.get_pos()
        for i, name in enumerate(self.TABS):
            tr  = pygame.Rect(8 + i*tab_w, tab_y, tab_w - 2, 28)
            self._tab_rects.append(tr)
            hov = tr.collidepoint(mx, my) and i != self._tab
            draw_btn(surf, tr, name, self._font_btn,
                     active=(i == self._tab), hover=hov)

        # Tab content — do NOT clear _fields here; _make_field preserves
        # focused/edited values across frames. Fields are only cleared on
        # explicit tab switch (handled in MOUSEBUTTONDOWN).
        content_y = tab_y + 38
        if   self._tab == 0: self._draw_tab_arena(surf, content_y)
        elif self._tab == 1: self._draw_tab_lights(surf, content_y)
        elif self._tab == 2: self._draw_tab_walls(surf, content_y)
        elif self._tab == 3: self._draw_tab_robot(surf, content_y)

    def _row(self, surf, label, name, y, val, x0=140, w=150):
        self._make_field(name, x0, y, w, val)
        self._draw_field(surf, name, label, label_w=x0-8)

    def _draw_tab_arena(self, surf, y0):
        a = self.arena
        self._row(surf, "Width (m):",     "aw",  y0,      a["width"])
        self._row(surf, "Height (m):",    "ah",  y0+38,   a["height"])
        self._row(surf, "Wall thick (m):","awt", y0+76,   a["wall_thickness"])

        # Apply button
        btn = pygame.Rect(140, y0+116, 150, 30)
        self._draw_btn(surf, btn, "Apply", name="apply_arena")

    def _draw_tab_lights(self, surf, y0):
        lights = self.arena["light_sources"]
        y = y0
        # List
        lt = self._font_sm.render(f"{len(lights)} light source(s)", True, C_TEXT_DIM)
        surf.blit(lt, (12, y)); y += 22

        for i, ls in enumerate(lights):
            sel = i == self._sel_light
            col = C_SEL if sel else C_TEXT
            bg  = pygame.Rect(8, y, PANEL_W-16, 22)
            if sel:
                pygame.draw.rect(surf, (50, 45, 25), bg, border_radius=3)
            lt2 = self._font_sm.render(
                f"  L{i}  x={ls['x']:.2f}  y={ls['y']:.2f}"
                f"  r={ls['radius']:.2f}  I={ls['intensity']:.1f}", True, col)
            surf.blit(lt2, (12, y+3)); y += 24

        y += 8
        if self._sel_light >= 0 and self._sel_light < len(lights):
            ls = lights[self._sel_light]
            self._row(surf, "x (m):",       "lx",  y,      ls["x"])
            self._row(surf, "y (m):",       "ly",  y+38,   ls["y"])
            self._row(surf, "Radius (m):",  "lr",  y+76,   ls["radius"])
            self._row(surf, "Intensity:",   "li",  y+114,  ls["intensity"])
            btn_upd = pygame.Rect(140, y+154, 70, 28)
            btn_del = pygame.Rect(220, y+154, 70, 28)
            self._draw_btn(surf, btn_upd, "Update", name="upd_light")
            self._draw_btn(surf, btn_del, "Delete", name="del_light", danger=True)
        else:
            ht = self._font_sm.render("Click canvas to place a light", True, C_TEXT_DIM)
            surf.blit(ht, (12, y))

    def _draw_tab_walls(self, surf, y0):
        walls = self.arena["internal_walls"]
        y = y0
        wt = self._font_sm.render(f"{len(walls)} internal wall(s)", True, C_TEXT_DIM)
        surf.blit(wt, (12, y)); y += 22

        for i, w in enumerate(walls):
            sel = i == self._sel_wall
            col = C_SEL if sel else C_TEXT
            bg  = pygame.Rect(8, y, PANEL_W-16, 22)
            if sel:
                pygame.draw.rect(surf, (25, 35, 55), bg, border_radius=3)
            wt2 = self._font_sm.render(
                f"  W{i}  ({w['x0']:.2f},{w['y0']:.2f})"
                f"→({w['x1']:.2f},{w['y1']:.2f})", True, col)
            surf.blit(wt2, (12, y+3)); y += 24

        y += 8
        if self._sel_wall >= 0 and self._sel_wall < len(walls):
            w = walls[self._sel_wall]
            self._row(surf, "Thickness (m):", "wt_sel", y, w.get("thickness", 0.05))
            btn_upd = pygame.Rect(140, y+40, 70, 28)
            btn_del = pygame.Rect(220, y+40, 70, 28)
            self._draw_btn(surf, btn_upd, "Update", name="upd_wall")
            self._draw_btn(surf, btn_del, "Delete", name="del_wall", danger=True)
        else:
            ht = self._font_sm.render("Click+drag on canvas to draw", True, C_TEXT_DIM)
            surf.blit(ht, (12, y))

    def _draw_tab_robot(self, surf, y0):
        rs = self.arena["robot_start"]
        y  = y0
        self._row(surf, "Start x (m):",  "rx",  y,      rs["x"])
        self._row(surf, "Start y (m):",  "ry",  y+38,   rs["y"])
        self._row(surf, "Heading (°):",  "rh",  y+76,   rs["heading_deg"])
        ht = self._font_sm.render(
            "0°=east  90°=north  180°=west", True, C_TEXT_DIM)
        surf.blit(ht, (12, y+116))
        btn = pygame.Rect(140, y+140, 150, 30)
        self._draw_btn(surf, btn, "Apply", name="apply_robot")

    def _draw_btn(self, surf, rect, label, name=None, danger=False):
        from robosim.theme import draw_btn
        if not hasattr(self, "_btn_rects"):
            self._btn_rects = {}
        if name:
            self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx, my)
        draw_btn(surf, rect, label, self._font_btn,
                 hover=hov, danger=danger)

    def _draw_bottom(self, surf):
        br = pygame.Rect(0, self._wh - BOTTOM_H, self._ww, BOTTOM_H)
        pygame.draw.rect(surf, C_PANEL, br)
        pygame.draw.line(surf, C_PANEL_EDGE, (0, br.top), (self._ww, br.top), 1)

        self._btn_rects = getattr(self, "_btn_rects", {})

        x = 12
        for label, name in [
            ("New",     "btn_new"),
            ("Open",    "btn_open"),
            ("Save",    "btn_save"),
            ("Save As", "btn_saveas"),
        ]:
            btn = pygame.Rect(x, br.top + 10, 90, 32)
            self._draw_btn(surf, btn, label, name=name)
            x += 100

        # Current file path
        path_str = os.path.basename(self.arena_path)
        dirty_str = " ●" if self._dirty else ""
        pt = self._font_sm.render(path_str + dirty_str,
                                   True,
                                   (255, 160, 60) if self._dirty else C_TEXT_DIM)
        surf.blit(pt, (x + 16, br.top + 18))

        # Status message
        age = time.monotonic() - self._status_t
        if age < 4.0:
            st = self._font_ui.render(self._status, True, self._status_col)
            surf.blit(st, (self._ww - st.get_width() - 12, br.top + 17))

    def _draw(self):
        self._screen.fill(C_BG)
        self._btn_rects = {}
        self._draw_canvas(self._screen)
        self._draw_panel(self._screen)
        self._draw_bottom(self._screen)
        self._draw_saveas_overlay(self._screen)
        pygame.display.flip()

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_canvas_click(self, pos, button):
        wx, wy = self._screen_to_world(*pos)
        aw, ah = self.arena["width"]/2, self.arena["height"]/2

        if self._tab == 1:  # Lights
            # Check if clicking existing light
            for i, ls in enumerate(self.arena["light_sources"]):
                scl = self._scale()
                sx, sy = self._world_to_screen(ls["x"], ls["y"])
                if math.hypot(pos[0]-sx, pos[1]-sy) <= max(8, ls["radius"]*scl):
                    self._sel_light = i
                    self._fields    = {}   # refresh edit fields for new selection
                    return
            # Place new light (clamp inside arena)
            wx = max(-aw+0.1, min(aw-0.1, wx))
            wy = max(-ah+0.1, min(ah-0.1, wy))
            self.arena["light_sources"].append(
                {"x": round(wx,3), "y": round(wy,3),
                 "intensity": 1.0, "radius": 0.4})
            self._sel_light = len(self.arena["light_sources"]) - 1
            self._fields    = {}   # refresh edit fields for new light
            self._dirty = True

        elif self._tab == 2:  # Walls — start drag
            # Check if clicking existing wall
            for i, w in enumerate(self.arena["internal_walls"]):
                sx0,sy0 = self._world_to_screen(w["x0"],w["y0"])
                sx1,sy1 = self._world_to_screen(w["x1"],w["y1"])
                # Distance from point to line segment
                d = self._pt_to_seg_dist(pos, (sx0,sy0), (sx1,sy1))
                if d < 8:
                    self._sel_wall = i
                    self._fields   = {}   # refresh edit fields for new selection
                    return
            wx = max(-aw, min(aw, wx))
            wy = max(-ah, min(ah, wy))
            self._drag_wall = (round(wx,3), round(wy,3))
            self._sel_wall  = -1

        elif self._tab == 3:  # Robot
            wx = max(-aw+ROBOT_RADIUS, min(aw-ROBOT_RADIUS, wx))
            wy = max(-ah+ROBOT_RADIUS, min(ah-ROBOT_RADIUS, wy))
            self.arena["robot_start"]["x"] = round(wx, 3)
            self.arena["robot_start"]["y"] = round(wy, 3)
            self._dirty = True

    def _handle_canvas_release(self, pos):
        if self._tab == 2 and self._drag_wall:
            wx, wy = self._screen_to_world(*pos)
            aw, ah = self.arena["width"]/2, self.arena["height"]/2
            wx = max(-aw, min(aw, wx))
            wy = max(-ah, min(ah, wy))
            x0, y0 = self._drag_wall
            if math.hypot(wx-x0, wy-y0) > 0.05:
                self.arena["internal_walls"].append({
                    "x0": x0, "y0": y0,
                    "x1": round(wx,3), "y1": round(wy,3),
                    "thickness": 0.05
                })
                self._sel_wall = len(self.arena["internal_walls"]) - 1
                self._dirty = True
            self._drag_wall = None

    def _handle_scroll(self, dy):
        if self._tab == 3:
            rs = self.arena["robot_start"]
            rs["heading_deg"] = (rs["heading_deg"] + dy * 5) % 360
            self._dirty = True

    def _handle_key(self, key):
        # Save As overlay intercepts all keys when active
        if getattr(self, "_saveas_active", False):
            if key == pygame.K_RETURN:
                name = self._saveas_value.strip()
                if name:
                    if not name.endswith(".json"):
                        name += ".json"
                    arena_dir = os.path.dirname(
                        os.path.abspath(self.arena_path))
                    path = os.path.join(arena_dir, name)
                    self.arena_path    = path
                    self._saveas_active = False
                    self._save()
            elif key == pygame.K_ESCAPE:
                self._saveas_active = False
            elif key == pygame.K_BACKSPACE:
                self._saveas_value = self._saveas_value[:-1]
            return

        if self._focused_field:
            f = self._fields.get(self._focused_field)
            if f:
                if key == pygame.K_BACKSPACE:
                    f["value"] = f["value"][:-1]
                elif key == pygame.K_RETURN or key == pygame.K_TAB:
                    self._focused_field = None
                elif key == pygame.K_ESCAPE:
                    self._focused_field = None
        else:
            if key == pygame.K_DELETE or key == pygame.K_BACKSPACE:
                if self._tab == 1 and self._sel_light >= 0:
                    self._delete_light()
                elif self._tab == 2 and self._sel_wall >= 0:
                    self._delete_wall()

    def _handle_text(self, char):
        if getattr(self, "_saveas_active", False):
            if char.isprintable() and char not in r'\/:*?"<>|':
                self._saveas_value += char
            return
        if self._focused_field:
            f = self._fields.get(self._focused_field)
            if f and char in "0123456789.-":
                f["value"] += char

    def _handle_btn(self, name):
        if name == "apply_arena":
            self.arena["width"]          = max(0.5, self._field_val("aw", 2.0))
            self.arena["height"]         = max(0.5, self._field_val("ah", 4.0))
            self.arena["wall_thickness"] = max(0.01, self._field_val("awt", 0.05))
            self._dirty = True
            self._set_status("Arena dimensions updated")

        elif name == "upd_light":
            if 0 <= self._sel_light < len(self.arena["light_sources"]):
                ls = self.arena["light_sources"][self._sel_light]
                ls["x"]         = self._field_val("lx", ls["x"])
                ls["y"]         = self._field_val("ly", ls["y"])
                ls["radius"]    = max(0.05, self._field_val("lr", ls["radius"]))
                ls["intensity"] = max(0.1,  self._field_val("li", ls["intensity"]))
                self._dirty = True
                self._set_status(f"Light {self._sel_light} updated")

        elif name == "del_light":
            self._delete_light()

        elif name == "upd_wall":
            if 0 <= self._sel_wall < len(self.arena["internal_walls"]):
                w = self.arena["internal_walls"][self._sel_wall]
                w["thickness"] = max(0.01, self._field_val("wt_sel", 0.05))
                self._dirty = True
                self._set_status(f"Wall {self._sel_wall} updated")

        elif name == "del_wall":
            self._delete_wall()

        elif name == "apply_robot":
            rs = self.arena["robot_start"]
            rs["x"]           = self._field_val("rx", rs["x"])
            rs["y"]           = self._field_val("ry", rs["y"])
            rs["heading_deg"] = self._field_val("rh", rs["heading_deg"]) % 360
            self._dirty = True
            self._set_status("Robot start pose updated")

        elif name == "btn_new":
            self.arena = dict(DEFAULT_ARENA)
            self.arena["light_sources"]  = []
            self.arena["internal_walls"] = []
            self.arena["robot_start"]    = {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
            self._sel_light = -1
            self._sel_wall  = -1
            self._dirty     = True
            self._set_status("New arena — use Save As to name it")

        elif name == "btn_open":
            self._open_file_dialog()

        elif name == "btn_save":
            self._save()

        elif name == "btn_saveas":
            self._save_as()

    def _delete_light(self):
        if 0 <= self._sel_light < len(self.arena["light_sources"]):
            self.arena["light_sources"].pop(self._sel_light)
            self._sel_light = -1
            self._dirty = True
            self._set_status("Light deleted")

    def _delete_wall(self):
        if 0 <= self._sel_wall < len(self.arena["internal_walls"]):
            self.arena["internal_walls"].pop(self._sel_wall)
            self._sel_wall = -1
            self._dirty = True
            self._set_status("Wall deleted")

    def _save(self):
        save_arena(self.arena, self.arena_path)
        self._dirty = False
        self._set_status(f"Saved → {os.path.basename(self.arena_path)}")

    def _open_file_dialog(self):
        """Cycle through JSON files in the same directory as the current arena file."""
        arena_dir  = os.path.dirname(os.path.abspath(self.arena_path))
        candidates = sorted(
            f for f in os.listdir(arena_dir)
            if f.endswith(".json") and not f.startswith(".")
        )
        if not candidates:
            self._set_status("No JSON files found", ok=False)
            return
        cur = os.path.basename(self.arena_path)
        try:
            idx = candidates.index(cur)
            nxt = candidates[(idx + 1) % len(candidates)]
        except ValueError:
            nxt = candidates[0]
        path = os.path.join(arena_dir, nxt)
        try:
            self.arena      = load_arena(path)
            self.arena_path = path
            self._sel_light = -1
            self._sel_wall  = -1
            self._fields    = {}
            self._dirty     = False
            self._set_status(f"Opened {nxt}")
        except Exception as e:
            self._set_status(f"Could not open {nxt}: {e}", ok=False)

    def _save_as(self):
        """Prompt for a new filename using a simple overlay input."""
        self._saveas_active = True
        self._saveas_value  = os.path.basename(self.arena_path)

    def _draw_saveas_overlay(self, surf):
        """Draw Save As input overlay and return True while active."""
        if not getattr(self, "_saveas_active", False):
            return False
        # Semi-transparent overlay
        overlay = pygame.Surface((self._ww, self._wh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surf.blit(overlay, (0, 0))
        # Dialog box
        dw, dh = 420, 130
        dx = (self._ww - dw) // 2
        dy = (self._wh - dh) // 2
        pygame.draw.rect(surf, (26, 30, 44), (dx, dy, dw, dh), border_radius=8)
        pygame.draw.rect(surf, C_PANEL_EDGE, (dx, dy, dw, dh), 1, border_radius=8)
        # Title
        tt = self._font_ui.render("Save As", True, C_HEADING)
        surf.blit(tt, (dx + 16, dy + 12))
        # Input field
        fr = pygame.Rect(dx + 16, dy + 48, dw - 32, 30)
        pygame.draw.rect(surf, (40, 48, 70), fr, border_radius=4)
        pygame.draw.rect(surf, C_ACCENT,    fr, 1,  border_radius=4)
        vt = self._font_ui.render(self._saveas_value, True, C_TEXT)
        surf.blit(vt, (fr.x + 6, fr.y + 6))
        # Hint
        ht = self._font_sm.render("Enter to confirm  |  Esc to cancel", True, C_TEXT_DIM)
        surf.blit(ht, (dx + 16, dy + 96))
        return True

    @staticmethod
    def _pt_to_seg_dist(pt, a, b):
        px, py = pt
        ax, ay = a
        bx, by = b
        dx, dy = bx-ax, by-ay
        if dx == dy == 0:
            return math.hypot(px-ax, py-ay)
        t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy) / (dx*dx+dy*dy)))
        return math.hypot(px - (ax+t*dx), py - (ay+t*dy))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            self._btn_rects = {}
            self._draw()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.VIDEORESIZE:
                    self._screen = pygame.display.set_mode(
                        event.size, pygame.RESIZABLE)

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos
                    cr  = self._canvas_rect

                    # Tab click
                    for i, tr in enumerate(getattr(self, "_tab_rects", [])):
                        if tr.collidepoint(pos):
                            self._tab = i
                            self._sel_light = -1
                            self._sel_wall  = -1
                            self._fields    = {}   # reinitialise fields for new tab
                            self._focused_field = None
                            break
                    else:
                        # Button click
                        clicked_btn = False
                        for name, rect in getattr(self, "_btn_rects", {}).items():
                            if rect.collidepoint(pos):
                                self._handle_btn(name)
                                clicked_btn = True
                                break

                        if not clicked_btn:
                            # Field click
                            clicked_field = False
                            for fname, f in self._fields.items():
                                if f["rect"].collidepoint(pos):
                                    self._focused_field = fname
                                    f["focus"] = True
                                    clicked_field = True
                                else:
                                    f["focus"] = False
                            if not clicked_field:
                                self._focused_field = None

                            # Canvas click
                            if cr.collidepoint(pos) and event.button == 1:
                                self._handle_canvas_click(pos, event.button)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        cr = self._canvas_rect
                        if cr.collidepoint(event.pos):
                            self._handle_canvas_release(event.pos)

                elif event.type == pygame.MOUSEWHEEL:
                    self._handle_scroll(event.y)

                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event.key)

                elif event.type == pygame.TEXTINPUT:
                    self._handle_text(event.text)

            self._clock.tick(30)

        pygame.quit()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="RoboSim Arena Builder")
    ap.add_argument("--arena", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "games", "ethology", "arena.json"))
    args = ap.parse_args()
    ArenaBuilder(arena_path=args.arena).run()
