"""
tools/arena_builder.py
-----------------------
Arena Builder — standalone PyGame editor for designing robot arenas.

Grid: 25 cm spacing, rendered as faint dots inside the arena boundary.
All placement snaps to the nearest grid dot.

Left panel tabs:
  [Arena]  — width, height, wall thickness (text fields + Apply)
  [Lights] — click grid dot to place; click existing light to select
  [Walls]  — two-click: dot for endpoint 1, dot for endpoint 2
              preview line is green (OK) or red (rejected)
  [Robot]  — click grid dot for start position; scroll to rotate heading

Interaction rules:
  Lights snap to any interior grid point (including near walls — lights
  are above walls in the physical world)
  Wall endpoints snap to grid points; walls may not cross or overlap
  existing walls (shared endpoints and T-junctions are allowed)
  Right-click or Delete key removes selected light / wall

Bottom bar:
  [New]  [Open]  [Save]  [Launch]          [Done]

Keyboard:
  Esc        cancel wall in progress / deselect
  Delete     remove selected light or wall
  Ctrl+Z     undo  (up to 40 steps)
  Ctrl+Y / Ctrl+Shift+Z  redo
  Ctrl+S     save

Colours always follow the currently-selected PAW theme.

Run:
  py -3.12 tools/arena_builder.py
  py -3.12 tools/arena_builder.py --arena path/to/arena.json
"""

import argparse
import copy
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

# ── Theme — applied before any colour import so all names reflect the
#    saved theme choice rather than the module-level default ───────────────────
import engine.theme as _T
_T.apply(_T.load_saved_theme())

# Import colour names that actually exist in engine/theme.py
from engine.theme import (
    BG           as C_BG,
    PANEL        as C_PANEL,
    PANEL_DEEP   as C_PANEL_DEEP,
    BORDER       as C_BORDER,
    BORDER_DIM   as C_BORDER_DIM,
    PHOSPHOR     as C_PHOSPHOR,
    PHOSPHOR_DIM as C_DIM,
    PHOSPHOR_MID as C_MID,
    AMBER        as C_AMBER,
    AMBER_DIM    as C_AMBER_DIM,
    TEXT         as C_TEXT,
    TEXT_DIM     as C_TEXT_DIM,
)

# Derived / semantic aliases
C_FLOOR      = C_PANEL_DEEP          # arena floor fill
C_GRID_DOT   = C_BORDER_DIM          # faint grid dots
C_WALL       = C_PHOSPHOR            # placed walls
C_WALL_SEL   = C_AMBER               # selected wall
C_WALL_BAD   = (180, 40, 40)         # rejected wall preview
C_LIGHT_RING = C_AMBER               # light ring colour
C_LIGHT_SEL  = C_PHOSPHOR            # selected light ring
C_ROBOT      = C_MID                 # robot silhouette
C_HANDLE     = C_AMBER               # drag handles / dots
C_STATUS_BG  = C_PANEL_DEEP          # status bar background
C_HEADING    = C_PHOSPHOR            # overlay headings

# ── Layout ────────────────────────────────────────────────────────────────────
PANEL_W  = 220   # px — left panel width
STATUS_H = 40    # px — bottom status / button bar height
MARGIN   = 40    # px — canvas margin around arena

# Grid
GRID_M   = 0.25  # metres between grid dots (25 cm)
DOT_R    = 3     # px — grid dot radius
HOVER_R  = 7     # px — hover highlight radius
WALL_HIT = 10    # px — click tolerance for selecting existing walls

# Undo depth
MAX_UNDO = 40

# Tab indices
TAB_ARENA  = 0
TAB_LIGHTS = 1
TAB_WALLS  = 2
TAB_ROBOT  = 3
TAB_NAMES  = ["Arena", "Lights", "Walls", "Robot"]


# ═════════════════════════════════════════════════════════════════════════════
# Arena data helpers
# ═════════════════════════════════════════════════════════════════════════════

def _default_arena():
    return {
        "width":          1.0,
        "height":         2.0,
        "wall_thickness": 0.05,
        "light_sources":  [{"x": 0.0, "y": 0.50, "intensity": 1.0, "radius": 0.35}],
        "internal_walls": [],
        "robot_start":    {"x": 0.0, "y": -0.60, "heading_deg": 90.0},
    }

def _load_arena(path):
    with open(path) as f:
        d = json.load(f)
    d.setdefault("internal_walls", [])
    d.setdefault("light_sources",  [])
    d.setdefault("robot_start",    {"x": 0.0, "y": -0.60, "heading_deg": 90.0})
    return d

def _save_arena(arena, path):
    with open(path, "w") as f:
        json.dump(arena, f, indent=4)


# ═════════════════════════════════════════════════════════════════════════════
# Geometry helpers
# ═════════════════════════════════════════════════════════════════════════════

def _cross2d(ax, ay, bx, by):
    return ax * by - ay * bx

def _seg_intersect_proper(ax, ay, bx, by, cx, cy, dx, dy):
    """True if segments AB and CD intersect at a non-endpoint interior point."""
    abx, aby = bx-ax, by-ay
    cdx, cdy = dx-cx, dy-cy
    denom = _cross2d(abx, aby, cdx, cdy)
    if abs(denom) < 1e-9:
        return False  # parallel / collinear handled separately
    acx, acy = cx-ax, cy-ay
    t = _cross2d(acx, acy, cdx, cdy) / denom
    u = _cross2d(acx, acy, abx, aby) / denom
    # Strictly interior on both (exclude shared endpoints)
    return 1e-6 < t < 1-1e-6 and 1e-6 < u < 1-1e-6

def _pts_close(ax, ay, bx, by, tol=1e-4):
    return abs(ax-bx) < tol and abs(ay-by) < tol

def _segs_collinear_overlap(ax, ay, bx, by, cx, cy, dx, dy):
    """True if collinear segments AB and CD overlap (not just touch at a point)."""
    # Check collinearity
    abx, aby = bx-ax, by-ay
    acx, acy = cx-ax, cy-ay
    adx, ady = dx-ax, dy-ay
    if abs(_cross2d(abx, aby, acx, acy)) > 1e-6:
        return False
    if abs(_cross2d(abx, aby, adx, ady)) > 1e-6:
        return False
    # Project onto AB axis
    lab2 = abx*abx + aby*aby
    if lab2 < 1e-12:
        return False
    tc = (acx*abx + acy*aby) / lab2
    td = (adx*abx + ady*aby) / lab2
    tlo, thi = min(tc,td), max(tc,td)
    # Overlap interval (excluding pure endpoint touch)
    overlap = min(thi, 1.0) - max(tlo, 0.0)
    return overlap > 1e-4

def _wall_conflicts(x0, y0, x1, y1, existing_walls, skip_idx=None):
    """
    Returns True if the proposed wall (x0,y0)-(x1,y1) conflicts with any
    existing wall.  Conflicts: proper crossing, collinear overlap, or exact
    duplicate.  Shared endpoints and T-junctions are allowed.
    """
    for i, w in enumerate(existing_walls):
        if i == skip_idx:
            continue
        wx0, wy0, wx1, wy1 = w["x0"], w["y0"], w["x1"], w["y1"]
        # Exact duplicate (either direction)
        if ((_pts_close(x0,y0,wx0,wy0) and _pts_close(x1,y1,wx1,wy1)) or
                (_pts_close(x0,y0,wx1,wy1) and _pts_close(x1,y1,wx0,wy0))):
            return True
        # Proper crossing
        if _seg_intersect_proper(x0,y0,x1,y1, wx0,wy0,wx1,wy1):
            return True
        # Collinear overlap
        if _segs_collinear_overlap(x0,y0,x1,y1, wx0,wy0,wx1,wy1):
            return True
    return False


# ═════════════════════════════════════════════════════════════════════════════
# ArenaBuilder
# ═════════════════════════════════════════════════════════════════════════════

class ArenaBuilder:

    def __init__(self, arena_path=None):
        pygame.init()
        pygame.key.set_repeat(400, 40)

        info = pygame.display.Info()
        self._ww = min(1400, info.current_w - 40)
        self._wh = min(880,  info.current_h - 80)
        self._screen = pygame.display.set_mode((self._ww, self._wh),
                                               pygame.RESIZABLE)

        self._font_ui  = pygame.font.SysFont("Courier New", 14, bold=True)
        self._font_md  = pygame.font.SysFont("Courier New", 13)
        self._font_sm  = pygame.font.SysFont("Courier New", 12)

        # ── Arena state ───────────────────────────────────────────────────────
        # _arena_path is the SAVE TARGET. When the builder is launched from a
        # game hub with --arena, that path is an OUTPUT SLOT the game reads back
        # after the editor exits (RE: arenas/session_current.json) — it is not
        # "the file the user is browsing". Opening another arena must therefore
        # load its CONTENT into the slot, not redirect where the slot writes.
        # _session_path records that distinction so Open cannot break it.
        self._arena_path   = arena_path
        self._session_path = arena_path        # None when run standalone
        self._loaded_from  = arena_path        # for the caption only
        if arena_path and os.path.exists(arena_path):
            self.arena = _load_arena(arena_path)
        else:
            self.arena = _default_arena()
        self._dirty    = False
        self._history: list = []
        self._redo_st: list = []

        # ── UI state ──────────────────────────────────────────────────────────
        self._tab        = TAB_LIGHTS
        self._status     = "Ready"
        self._running    = True

        # Selection
        self._sel_light  = None   # index into arena["light_sources"]
        self._sel_wall   = None   # index into arena["internal_walls"]

        # Wall placement state
        self._wall_p0    = None   # first endpoint (wx, wy) or None

        # Hover
        self._hover_pt   = None   # nearest grid point (wx, wy) to mouse

        # Overlays
        self._saveas_active = False
        self._saveas_val    = ""
        self._confirm_done  = False   # "Done pressed while dirty" dialog

        # Text fields for Arena tab
        self._fields     = {}
        self._focused    = None
        self._setup_arena_fields()
        self._light_btns = {}

        self._update_caption()

    # ── Caption ───────────────────────────────────────────────────────────────

    def _update_caption(self):
        _shown = self._loaded_from or self._arena_path
        name = os.path.basename(_shown) if _shown else "unsaved"
        dirty = " ●" if self._dirty else ""
        pygame.display.set_caption(f"PAW — Arena Builder — {name}{dirty}")

    # ── Coordinate conversion ─────────────────────────────────────────────────

    def _canvas_rect(self):
        return pygame.Rect(PANEL_W, 0,
                           self._ww - PANEL_W,
                           self._wh - STATUS_H)

    def _scale(self):
        cr = self._canvas_rect()
        aw = self.arena["width"]
        ah = self.arena["height"]
        return min((cr.width  - MARGIN * 2) / aw,
                   (cr.height - MARGIN * 2) / ah)

    def _w2s(self, wx, wy):
        """World → screen."""
        cr  = self._canvas_rect()
        scl = self._scale()
        cx  = cr.left + cr.width  // 2
        cy  = cr.top  + cr.height // 2
        return (int(cx + wx * scl), int(cy - wy * scl))

    def _s2w(self, sx, sy):
        """Screen → world."""
        cr  = self._canvas_rect()
        scl = self._scale()
        cx  = cr.left + cr.width  // 2
        cy  = cr.top  + cr.height // 2
        return ((sx - cx) / scl, (cy - sy) / scl)

    # ── Grid helpers ──────────────────────────────────────────────────────────

    def _grid_points(self, interior_only=False):
        """Yield (wx, wy) for every valid grid point inside the arena."""
        aw = self.arena["width"]
        ah = self.arena["height"]
        margin = GRID_M * 0.01
        x = round(math.ceil(-aw/2 / GRID_M) * GRID_M, 9)
        while x <= aw/2 + margin:
            y = round(math.ceil(-ah/2 / GRID_M) * GRID_M, 9)
            while y <= ah/2 + margin:
                if interior_only:
                    if (abs(x) < aw/2 - margin and abs(y) < ah/2 - margin):
                        yield round(x, 4), round(y, 4)
                else:
                    yield round(x, 4), round(y, 4)
                y = round(y + GRID_M, 9)
            x = round(x + GRID_M, 9)

    def _nearest_grid(self, sx, sy):
        """Return world coords of nearest grid point to screen pos, or None."""
        wx, wy = self._s2w(sx, sy)
        best = None
        best_d = float("inf")
        for gx, gy in self._grid_points():
            d = math.hypot(wx-gx, wy-gy)
            if d < best_d:
                best_d = d
                best = (gx, gy)
        if best is None:
            return None
        # Only accept if within HOVER_R pixels
        sx2, sy2 = self._w2s(*best)
        if math.hypot(sx-sx2, sy-sy2) <= HOVER_R * 2.5:
            return best
        return None

    # ── Undo / redo ───────────────────────────────────────────────────────────

    def _push_undo(self):
        self._history.append(copy.deepcopy(self.arena))
        if len(self._history) > MAX_UNDO:
            self._history.pop(0)
        self._redo_st.clear()

    def _undo(self):
        if not self._history:
            return
        self._redo_st.append(copy.deepcopy(self.arena))
        self.arena = self._history.pop()
        self._dirty = True
        self._deselect()
        self._update_caption()

    def _redo(self):
        if not self._redo_st:
            return
        self._history.append(copy.deepcopy(self.arena))
        self.arena = self._redo_st.pop()
        self._dirty = True
        self._deselect()
        self._update_caption()

    def _deselect(self):
        self._sel_light = None
        self._sel_wall  = None
        self._wall_p0   = None

    # ── Save / load ───────────────────────────────────────────────────────────

    def _save(self, path=None):
        p = path or self._arena_path
        if not p:
            self._saveas_active = True
            self._saveas_val    = ""
            return False
        _save_arena(self.arena, p)
        self._arena_path = p
        self._dirty      = False
        self._update_caption()
        self._status = f"Saved: {os.path.basename(p)}"
        return True

    def _load_dialog(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw()
            path = filedialog.askopenfilename(
                title="Open Arena",
                filetypes=[("Arena JSON", "*.json"), ("All files", "*.*")])
            root.destroy()
            if path:
                self._push_undo()
                self.arena = _load_arena(path)
                self._loaded_from = path
                if self._session_path:
                    # Keep writing to the game's slot. Opening an arena means
                    # "use this arena", so the slot now differs from what is on
                    # disk there — mark dirty so Done/Save actually writes it.
                    self._arena_path = self._session_path
                    self._dirty = True
                else:
                    self._arena_path = path
                    self._dirty = False
                self._deselect()
                self._setup_arena_fields()
                self._update_caption()
                self._status = f"Loaded: {os.path.basename(path)}"
        except Exception as e:
            self._status = f"Load error: {e}"

    def _request_done(self):
        # A session slot is always written on Done, even if the user only
        # opened an arena and changed nothing: exiting the editor should leave
        # the game running whatever is on screen.
        if self._session_path and self._arena_path:
            if self._save():
                self._running = False
            return
        if self._dirty and self._arena_path:
            # Auto-save when launched from hub (path is pre-set)
            ok = self._save()
            if ok:
                self._running = False
        elif self._dirty:
            # No path yet — must prompt
            self._confirm_done = True
        else:
            self._running = False

    # ── Arena tab fields ──────────────────────────────────────────────────────

    def _setup_arena_fields(self):
        a = self.arena
        self._fields = {
            "width":      str(round(a["width"],      3)),
            "height":     str(round(a["height"],     3)),
            "thickness":  str(round(a["wall_thickness"], 3)),
        }
        self._focused = None

    def _apply_arena_fields(self):
        try:
            w  = float(self._fields["width"])
            h  = float(self._fields["height"])
            th = float(self._fields["thickness"])
            if w > 0.1 and h > 0.1 and th > 0:
                self._push_undo()
                self.arena["width"]          = round(w,  3)
                self.arena["height"]         = round(h,  3)
                self.arena["wall_thickness"] = round(th, 3)
                self._dirty = True
                self._update_caption()
                self._status = "Arena dimensions updated"
        except ValueError:
            self._status = "Invalid number in arena fields"

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self):
        self._screen.fill(C_BG)
        self._draw_panel()
        self._draw_canvas()
        self._draw_status_bar()
        if self._saveas_active:
            self._draw_saveas()
        if self._confirm_done:
            self._draw_confirm_done()
        pygame.display.flip()

    # ── Panel ─────────────────────────────────────────────────────────────────

    def _draw_panel(self):
        pr = pygame.Rect(0, 0, PANEL_W, self._wh - STATUS_H)
        pygame.draw.rect(self._screen, C_PANEL, pr)
        pygame.draw.line(self._screen, C_BORDER,
                         (PANEL_W-1, 0), (PANEL_W-1, self._wh-STATUS_H), 1)

        # Tab buttons
        tw = PANEL_W // len(TAB_NAMES)
        for i, name in enumerate(TAB_NAMES):
            tr = pygame.Rect(i*tw, 0, tw, 30)
            active = (i == self._tab)
            pygame.draw.rect(self._screen,
                             C_PHOSPHOR if active else C_PANEL_DEEP, tr)
            pygame.draw.rect(self._screen, C_BORDER, tr, 1)
            tc = C_BG if active else C_TEXT_DIM
            tt = self._font_sm.render(name, True, tc)
            self._screen.blit(tt, (tr.centerx - tt.get_width()//2,
                                   tr.centery - tt.get_height()//2))

        y = 38
        if self._tab == TAB_ARENA:
            y = self._draw_panel_arena(y)
        elif self._tab == TAB_LIGHTS:
            y = self._draw_panel_lights(y)
        elif self._tab == TAB_WALLS:
            y = self._draw_panel_walls(y)
        elif self._tab == TAB_ROBOT:
            y = self._draw_panel_robot(y)

    def _draw_field(self, y, label, key):
        """Draw a labelled text field. Returns new y."""
        lbl = self._font_sm.render(label, True, C_TEXT_DIM)
        self._screen.blit(lbl, (8, y))
        fr = pygame.Rect(8, y+16, PANEL_W-16, 24)
        focused = (self._focused == key)
        pygame.draw.rect(self._screen, C_BG, fr, border_radius=3)
        pygame.draw.rect(self._screen,
                         C_PHOSPHOR if focused else C_BORDER_DIM,
                         fr, 1, border_radius=3)
        val = self._fields.get(key, "") + ("|" if focused else "")
        vt  = self._font_sm.render(val, True, C_PHOSPHOR if focused else C_TEXT)
        self._screen.blit(vt, (fr.x+5, fr.y+5))
        setattr(self, f"_fr_{key}", fr)
        return y + 48

    def _draw_panel_arena(self, y):
        y = self._draw_field(y, "Width (m):", "width")
        y = self._draw_field(y, "Height (m):", "height")
        y = self._draw_field(y, "Wall thickness (m):", "thickness")
        br = pygame.Rect(8, y, PANEL_W-16, 28)
        pygame.draw.rect(self._screen, C_BORDER_DIM, br, 1, border_radius=4)
        at = self._font_sm.render("Apply", True, C_TEXT)
        self._screen.blit(at, (br.centerx-at.get_width()//2,
                                br.centery-at.get_height()//2))
        self._apply_btn = br
        return y + 36

    def _draw_panel_lights(self, y):
        self._light_btns = {}
        inst = [
            "Click a grid dot to",
            "place a light source.",
            "Click existing light",
            "to select it.",
            "Right-click / Delete",
            "to remove selected.",
        ]
        for line in inst:
            lt = self._font_sm.render(line, True, C_TEXT_DIM)
            self._screen.blit(lt, (8, y)); y += 15
        y += 6

        if self._sel_light is not None:
            ls = self.arena["light_sources"][self._sel_light]
            t = self._font_sm.render(f"Light L{self._sel_light}", True, C_AMBER)
            self._screen.blit(t, (8, y)); y += 18

            # Intensity control
            t = self._font_sm.render("Intensity:", True, C_TEXT_DIM)
            self._screen.blit(t, (8, y)); y += 14
            y = self._draw_spin(y, "light_intensity",
                                f"{ls['intensity']:.2f}",
                                step_label=("−", "+"))
            y += 4

            # Radius control
            t = self._font_sm.render("Radius (m):", True, C_TEXT_DIM)
            self._screen.blit(t, (8, y)); y += 14
            y = self._draw_spin(y, "light_radius",
                                f"{ls['radius']:.2f}m",
                                step_label=("−", "+"))
            y += 8

            # Color toggle W/R/G/B
            ct = self._font_sm.render("Color:", True, C_DIM)
            self._screen.blit(ct, (8, y)); y += ct.get_height() + 3
            lc = ls.get("color", "white")
            _LC = {"white": (220, 200, 130), "red":   (220, 60,  60),
                   "green": ( 60, 200,  60), "blue":  ( 80, 140, 220)}
            bw = (PANEL_W - 16 - 6) // 4
            for ci, cn in enumerate(["white", "red", "green", "blue"]):
                br = pygame.Rect(8 + ci * (bw + 2), y, bw, 22)
                active = (lc == cn)
                pygame.draw.rect(self._screen,
                                 _LC[cn] if active else C_BG,
                                 br, border_radius=3)
                pygame.draw.rect(self._screen, _LC[cn], br, 1,
                                 border_radius=3)
                lt = self._font_sm.render(
                    cn[0].upper(), True,
                    (10, 10, 10) if active else _LC[cn])
                self._screen.blit(
                    lt, (br.centerx - lt.get_width()//2,
                         br.centery - lt.get_height()//2))
                self._light_btns[f"lc_{cn}"] = br
            y += 30

            pos_t = self._font_sm.render(
                f"({ls['x']:.2f}, {ls['y']:.2f})", True, C_DIM)
            self._screen.blit(pos_t, (8, y)); y += 16

        return y

    def _draw_spin(self, y, key, value_str, step_label=("−","+")):
        """Draw a −  [value]  + row. Returns new y. Stores btn rects."""
        bw = 22; gap = 4
        vw = PANEL_W - 16 - bw*2 - gap*2
        minus_r = pygame.Rect(8,           y, bw, 22)
        val_r   = pygame.Rect(8+bw+gap,    y, vw, 22)
        plus_r  = pygame.Rect(8+bw+gap+vw+gap, y, bw, 22)
        for r, lbl in [(minus_r, step_label[0]), (plus_r, step_label[1])]:
            pygame.draw.rect(self._screen, C_BORDER_DIM, r, 1, border_radius=3)
            lt = self._font_ui.render(lbl, True, C_TEXT)
            self._screen.blit(lt, (r.centerx-lt.get_width()//2,
                                   r.centery-lt.get_height()//2))
        pygame.draw.rect(self._screen, C_BG, val_r, border_radius=3)
        pygame.draw.rect(self._screen, C_BORDER_DIM, val_r, 1, border_radius=3)
        vt = self._font_sm.render(value_str, True, C_PHOSPHOR)
        self._screen.blit(vt, (val_r.centerx-vt.get_width()//2,
                                val_r.centery-vt.get_height()//2))
        self._light_btns[f"{key}_minus"] = minus_r
        self._light_btns[f"{key}_plus"]  = plus_r
        return y + 26

    def _draw_panel_walls(self, y):
        inst = [
            "Click dot for wall",
            "endpoint 1, then",
            "endpoint 2.",
            "",
            "Green = valid.",
            "Red   = conflicts.",
            "",
            "Esc cancels.",
            "Click wall to select.",
            "Right-click / Delete",
            "to remove.",
        ]
        for line in inst:
            lt = self._font_sm.render(line, True, C_TEXT_DIM)
            self._screen.blit(lt, (8, y)); y += 16
        if self._wall_p0:
            y += 4
            t = self._font_sm.render("P1 set — pick P2", True, C_PHOSPHOR)
            self._screen.blit(t, (8, y)); y += 16
        if self._sel_wall is not None:
            y += 8
            w = self.arena["internal_walls"][self._sel_wall]
            info = [
                f"Selected: W{self._sel_wall}",
                f"  ({w['x0']:.2f},{w['y0']:.2f})",
                f"  ({w['x1']:.2f},{w['y1']:.2f})",
            ]
            for line in info:
                t = self._font_sm.render(line, True, C_AMBER)
                self._screen.blit(t, (8, y)); y += 16
        return y

    def _draw_panel_robot(self, y):
        rs = self.arena["robot_start"]
        inst = [
            "Click a grid dot to",
            "set start position.",
            "",
            "Scroll wheel to",
            "rotate heading.",
            "",
            f"x={rs['x']:.2f}m",
            f"y={rs['y']:.2f}m",
            f"hdg={rs['heading_deg']:.0f}°",
        ]
        for line in inst:
            t = self._font_sm.render(line, True, C_TEXT_DIM)
            self._screen.blit(t, (8, y)); y += 16
        return y

    # ── Canvas ────────────────────────────────────────────────────────────────

    def _draw_canvas(self):
        cr  = self._canvas_rect()
        scl = self._scale()
        aw  = self.arena["width"]
        ah  = self.arena["height"]

        pygame.draw.rect(self._screen, C_BG, cr)

        # Arena floor
        tl = self._w2s(-aw/2,  ah/2)
        br = self._w2s( aw/2, -ah/2)
        floor_r = pygame.Rect(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1])
        pygame.draw.rect(self._screen, C_FLOOR, floor_r)

        # Grid dots
        for gx, gy in self._grid_points():
            sx, sy = self._w2s(gx, gy)
            if cr.collidepoint(sx, sy):
                pygame.draw.circle(self._screen, C_GRID_DOT, (sx, sy), DOT_R)

        # Hover highlight
        if self._hover_pt:
            hx, hy = self._w2s(*self._hover_pt)
            pygame.draw.circle(self._screen, C_PHOSPHOR, (hx, hy), HOVER_R, 2)

        # Arena border
        wt = max(2, int(self.arena["wall_thickness"] * scl))
        pygame.draw.rect(self._screen, C_BORDER,
                         pygame.Rect(tl[0]-wt, tl[1]-wt,
                                     br[0]-tl[0]+wt*2, br[1]-tl[1]+wt*2), wt)

        # Internal walls
        for i, w in enumerate(self.arena["internal_walls"]):
            x0s, y0s = self._w2s(w["x0"], w["y0"])
            x1s, y1s = self._w2s(w["x1"], w["y1"])
            col = C_WALL_SEL if i == self._sel_wall else C_WALL
            pygame.draw.line(self._screen, col, (x0s,y0s), (x1s,y1s),
                             max(2, int(w.get("thickness", 0.05) * scl)))
            # Endpoint dots
            for px, py in [(x0s,y0s),(x1s,y1s)]:
                pygame.draw.circle(self._screen, col, (px,py), DOT_R+1)

        # Wall placement preview
        if self._wall_p0 and self._hover_pt:
            x0s, y0s = self._w2s(*self._wall_p0)
            x1s, y1s = self._w2s(*self._hover_pt)
            ok = not _wall_conflicts(
                self._wall_p0[0], self._wall_p0[1],
                self._hover_pt[0], self._hover_pt[1],
                self.arena["internal_walls"])
            # Don't flag zero-length as conflict, just don't show
            if not (self._wall_p0 == self._hover_pt):
                col = C_WALL if ok else C_WALL_BAD
                pygame.draw.line(self._screen, col, (x0s,y0s), (x1s,y1s), 2)
            # P0 dot
            pygame.draw.circle(self._screen, C_PHOSPHOR, (x0s,y0s), HOVER_R)

        # Light sources
        for i, ls in enumerate(self.arena["light_sources"]):
            self._draw_light(ls, i == self._sel_light)

        # Robot start
        self._draw_robot()

    def _draw_light(self, ls, selected):
        scl    = self._scale()
        cx, cy = self._w2s(ls["x"], ls["y"])
        r_px   = max(4, int(ls["radius"] * scl))
        intens = max(0.05, min(1.0, ls["intensity"]))
        # Glow
        for ring in range(r_px, 0, max(1, r_px//8)):
            alpha = int(90 * intens * (1.0 - ring/r_px))
            s = pygame.Surface((ring*2+2, ring*2+2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*C_AMBER[:3], alpha), (ring+1, ring+1), ring)
            self._screen.blit(s, (cx-ring-1, cy-ring-1))
        col = C_LIGHT_SEL if selected else C_LIGHT_RING
        pygame.draw.circle(self._screen, col, (cx, cy), r_px, 2)
        pygame.draw.circle(self._screen, col, (cx, cy), DOT_R+1)

    def _draw_robot(self):
        rs  = self.arena["robot_start"]
        scl = self._scale()
        cx, cy = self._w2s(rs["x"], rs["y"])
        r_px = max(6, int(0.077 * scl))
        pygame.draw.circle(self._screen, C_ROBOT, (cx, cy), r_px, 2)
        hdg   = math.radians(rs["heading_deg"])
        alen  = max(r_px + 8, int(0.12 * scl))
        tip_x = int(cx + math.cos(hdg) * alen)
        tip_y = int(cy - math.sin(hdg) * alen)
        pygame.draw.line(self._screen, C_ROBOT, (cx, cy), (tip_x, tip_y), 2)
        pygame.draw.circle(self._screen, C_HANDLE, (tip_x, tip_y), 4)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _draw_status_bar(self):
        sr = pygame.Rect(0, self._wh - STATUS_H, self._ww, STATUS_H)
        pygame.draw.rect(self._screen, C_STATUS_BG, sr)
        pygame.draw.line(self._screen, C_BORDER,
                         (0, self._wh - STATUS_H),
                         (self._ww, self._wh - STATUS_H), 1)

        # Buttons: New  Open  Save  Launch
        bx = PANEL_W + 8
        self._bar_btns = {}
        for label in ["New", "Open", "Save", "Launch"]:
            bw = self._font_md.size(label)[0] + 20
            br = pygame.Rect(bx, self._wh - STATUS_H + 4, bw, STATUS_H - 8)
            pygame.draw.rect(self._screen, C_BORDER_DIM, br, 1, border_radius=3)
            lt = self._font_sm.render(label, True, C_TEXT_DIM)
            self._screen.blit(lt, (br.centerx - lt.get_width()//2,
                                   br.centery - lt.get_height()//2))
            self._bar_btns[label] = br
            bx += bw + 8

        # Status message (centre)
        mx = self._screen.get_rect().centerx
        st = self._font_sm.render(self._status, True, C_DIM)
        self._screen.blit(st, (mx - st.get_width()//2,
                                self._wh - STATUS_H + 8))

        # Done button (right)
        dw = self._font_md.size("Done")[0] + 24
        dr = pygame.Rect(self._ww - dw - 8, self._wh - STATUS_H + 4,
                         dw, STATUS_H - 8)
        pygame.draw.rect(self._screen, C_PHOSPHOR, dr, 0, border_radius=3)
        dt = self._font_md.render("Done", True, C_BG)
        self._screen.blit(dt, (dr.centerx - dt.get_width()//2,
                                dr.centery - dt.get_height()//2))
        self._done_btn = dr

    # ── Overlays ──────────────────────────────────────────────────────────────

    def _draw_saveas(self):
        ov = pygame.Surface((self._ww, self._wh), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        self._screen.blit(ov, (0, 0))
        dw, dh = 480, 120
        dx = (self._ww - dw) // 2
        dy = (self._wh - dh) // 2
        pygame.draw.rect(self._screen, C_PANEL,     (dx,dy,dw,dh), border_radius=8)
        pygame.draw.rect(self._screen, C_BORDER,    (dx,dy,dw,dh), 1, border_radius=8)
        tt = self._font_ui.render("Save As — filename:", True, C_HEADING)
        self._screen.blit(tt, (dx+16, dy+12))
        ir = pygame.Rect(dx+16, dy+40, dw-32, 26)
        pygame.draw.rect(self._screen, C_BG, ir, border_radius=3)
        pygame.draw.rect(self._screen, C_PHOSPHOR, ir, 1, border_radius=3)
        vt = self._font_md.render(self._saveas_val + "|", True, C_PHOSPHOR)
        self._screen.blit(vt, (ir.x+6, ir.y+5))
        ht = self._font_sm.render("Enter to confirm  ·  Esc to cancel",
                                   True, C_DIM)
        self._screen.blit(ht, (dx+16, dy+80))

    def _draw_confirm_done(self):
        ov = pygame.Surface((self._ww, self._wh), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 180))
        self._screen.blit(ov, (0, 0))
        dw, dh = 440, 140
        dx = (self._ww - dw) // 2
        dy = (self._wh - dh) // 2
        pygame.draw.rect(self._screen, C_PANEL,  (dx,dy,dw,dh), border_radius=8)
        pygame.draw.rect(self._screen, C_BORDER, (dx,dy,dw,dh), 1, border_radius=8)
        tt = self._font_ui.render("Unsaved changes", True, C_HEADING)
        self._screen.blit(tt, (dx+16, dy+14))
        mt = self._font_sm.render("Save before closing?", True, C_TEXT)
        self._screen.blit(mt, (dx+16, dy+42))
        bw, bh, gap = 120, 32, 10
        bx = dx + (dw - bw*3 - gap*2) // 2
        by = dy + dh - bh - 14
        self._done_btns = {}
        for label, key in [("Save","save"),("Save As","saveas"),("Discard","discard")]:
            br = pygame.Rect(bx, by, bw, bh)
            accent = (key == "save")
            pygame.draw.rect(self._screen,
                             C_PHOSPHOR if accent else C_BORDER_DIM,
                             br, 0 if accent else 1, border_radius=4)
            lt = self._font_sm.render(label, True, C_BG if accent else C_TEXT)
            self._screen.blit(lt, (br.centerx - lt.get_width()//2,
                                   br.centery - lt.get_height()//2))
            self._done_btns[key] = br
            bx += bw + gap

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_mousedown(self, pos, button):
        sx, sy = pos

        # ── Confirm-Done overlay ──────────────────────────────────────────────
        if self._confirm_done:
            for key, br in self._done_btns.items():
                if br.collidepoint(sx, sy):
                    if key == "save":
                        ok = self._save()
                        if ok:
                            self._running = False
                    elif key == "saveas":
                        self._confirm_done = False
                        self._saveas_active = True
                        self._saveas_val    = ""
                        self._saveas_for_done = True
                    elif key == "discard":
                        self._running = False
            return

        # ── Save As overlay ───────────────────────────────────────────────────
        if self._saveas_active:
            return

        # ── Status bar buttons ────────────────────────────────────────────────
        if sy >= self._wh - STATUS_H:
            if hasattr(self, "_done_btn") and self._done_btn.collidepoint(sx, sy):
                self._request_done()
                return
            for label, br in self._bar_btns.items():
                if br.collidepoint(sx, sy):
                    self._handle_bar_btn(label)
                    return
            return

        # ── Panel ─────────────────────────────────────────────────────────────
        if sx < PANEL_W:
            self._handle_panel_click(sx, sy, button)
            return

        # ── Canvas ────────────────────────────────────────────────────────────
        cr = self._canvas_rect()
        if not cr.collidepoint(sx, sy):
            return

        if button == 3:
            self._handle_canvas_rclick(sx, sy)
            return

        if button == 1:
            self._handle_canvas_lclick(sx, sy)

    def _handle_bar_btn(self, label):
        if label == "New":
            if self._dirty:
                self._confirm_done = True
            else:
                self._push_undo()
                # Use default.json if it exists
                _def_paths = [
                    os.path.join(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))),
                        "games", "ethology", "arenas", "default.json"),
                ]
                _def = next((p for p in _def_paths
                             if os.path.exists(p)), None)
                self.arena = (_load_arena(_def)
                              if _def else _default_arena())
                self._arena_path = None
                self._dirty = False
                self._deselect()
                self._setup_arena_fields()
                self._update_caption()
                self._status = "New arena"
        elif label == "Open":
            self._load_dialog()
        elif label == "Save":
            self._save()
        elif label == "Launch":
            self._save()
            if not self._saveas_active and self._arena_path:
                root = os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))
                subprocess.Popen([sys.executable,
                                  os.path.join(root, "main.py"),
                                  "--arena", self._arena_path])
                self._running = False

    def _handle_panel_click(self, sx, sy, button):
        # Tab switching
        tw = PANEL_W // len(TAB_NAMES)
        if sy < 30:
            self._tab = sx // tw
            self._deselect()
            return

        if self._tab == TAB_LIGHTS and self._sel_light is not None:
            light_btns = getattr(self, "_light_btns", {})
            ls = self.arena["light_sources"][self._sel_light]
            if button == 1:
                for btn_key, br in light_btns.items():
                    if br.collidepoint(sx, sy):
                        self._push_undo()
                        if btn_key == "light_intensity_minus":
                            ls["intensity"] = round(max(0.1, ls["intensity"] - 0.1), 2)
                        elif btn_key == "light_intensity_plus":
                            ls["intensity"] = round(min(3.0, ls["intensity"] + 0.1), 2)
                        elif btn_key == "light_radius_minus":
                            ls["radius"] = round(max(0.05, ls["radius"] - 0.05), 2)
                        elif btn_key == "light_radius_plus":
                            ls["radius"] = round(min(2.0, ls["radius"] + 0.05), 2)
                        elif btn_key.startswith("lc_"):
                            ls["color"] = btn_key[3:]
                        self._dirty = True
                        self._update_caption()
                        return

        if self._tab == TAB_ARENA:
            # Field focus
            for key in ("width", "height", "thickness"):
                fr = getattr(self, f"_fr_{key}", None)
                if fr and fr.collidepoint(sx, sy):
                    if self._focused != key:
                        self._fields[key] = ""
                    self._focused = key
                    return
            self._focused = None
            # Apply button
            if hasattr(self, "_apply_btn") and self._apply_btn.collidepoint(sx, sy):
                self._apply_arena_fields()

    def _handle_canvas_lclick(self, sx, sy):
        gp = self._nearest_grid(sx, sy)

        if self._tab == TAB_LIGHTS:
            # Select existing light first
            for i, ls in enumerate(self.arena["light_sources"]):
                lsx, lsy = self._w2s(ls["x"], ls["y"])
                if math.hypot(sx-lsx, sy-lsy) <= HOVER_R * 2:
                    self._sel_light = i
                    self._sel_wall  = None
                    self._status = f"Selected light L{i}"
                    return
            # Place new light at grid point
            if gp:
                self._push_undo()
                self.arena["light_sources"].append({
                    "x": gp[0], "y": gp[1],
                    "intensity": 1.0, "radius": 0.25,
                    "color": "white"
                })
                self._sel_light = len(self.arena["light_sources"]) - 1
                self._sel_wall  = None
                self._dirty = True
                self._update_caption()
                self._status = f"Light placed at ({gp[0]:.2f}, {gp[1]:.2f})"

        elif self._tab == TAB_WALLS:
            if gp is None:
                self._status = "Click on a grid dot"
                return
            if self._wall_p0 is None:
                # First endpoint
                self._wall_p0 = gp
                self._sel_wall = None
                self._status = f"P1=({gp[0]:.2f},{gp[1]:.2f}) — click P2"
            else:
                # Second endpoint — place or reject
                if gp == self._wall_p0:
                    self._wall_p0 = None
                    self._status = "Same point — cancelled"
                    return
                x0, y0 = self._wall_p0
                x1, y1 = gp
                if _wall_conflicts(x0, y0, x1, y1, self.arena["internal_walls"]):
                    self._status = "Wall conflicts — choose a different endpoint"
                    # Keep P1 so user can try another P2
                else:
                    self._push_undo()
                    self.arena["internal_walls"].append({
                        "x0": round(x0,4), "y0": round(y0,4),
                        "x1": round(x1,4), "y1": round(y1,4),
                        "thickness": self.arena["wall_thickness"],
                    })
                    self._sel_wall = len(self.arena["internal_walls"]) - 1
                    self._wall_p0  = None
                    self._dirty    = True
                    self._update_caption()
                    self._status = f"Wall placed"

        elif self._tab == TAB_ROBOT:
            if gp:
                self._push_undo()
                self.arena["robot_start"]["x"] = gp[0]
                self.arena["robot_start"]["y"] = gp[1]
                self._dirty = True
                self._update_caption()
                self._status = f"Robot start set to ({gp[0]:.2f},{gp[1]:.2f})"

    def _handle_canvas_rclick(self, sx, sy):
        # Right-click removes selected or hit object
        if self._tab == TAB_LIGHTS:
            for i, ls in enumerate(self.arena["light_sources"]):
                lsx, lsy = self._w2s(ls["x"], ls["y"])
                if math.hypot(sx-lsx, sy-lsy) <= HOVER_R * 2:
                    self._push_undo()
                    self.arena["light_sources"].pop(i)
                    self._sel_light = None
                    self._dirty = True
                    self._update_caption()
                    self._status = f"Light L{i} removed"
                    return
        elif self._tab == TAB_WALLS:
            scl = self._scale()
            for i, w in enumerate(self.arena["internal_walls"]):
                x0s,y0s = self._w2s(w["x0"],w["y0"])
                x1s,y1s = self._w2s(w["x1"],w["y1"])
                d = self._pt_seg_dist((sx,sy),(x0s,y0s),(x1s,y1s))
                if d < WALL_HIT:
                    self._push_undo()
                    self.arena["internal_walls"].pop(i)
                    self._sel_wall = None
                    self._wall_p0  = None
                    self._dirty = True
                    self._update_caption()
                    self._status = f"Wall W{i} removed"
                    return

    def _pt_seg_dist(self, pt, a, b):
        px,py = pt; ax,ay = a; bx,by = b
        dx,dy = bx-ax, by-ay
        lsq = dx*dx + dy*dy
        if lsq < 1e-9:
            return math.hypot(px-ax, py-ay)
        t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/lsq))
        return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

    def _handle_mousemotion(self, pos):
        sx, sy = pos
        cr = self._canvas_rect()
        if cr.collidepoint(sx, sy):
            gp = self._nearest_grid(sx, sy)
            self._hover_pt = gp
        else:
            self._hover_pt = None

    def _handle_scroll(self, dy, pos):
        if self._tab == TAB_LIGHTS and self._sel_light is not None:
            # Scroll adjusts intensity of selected light
            ls = self.arena["light_sources"][self._sel_light]
            ls["intensity"] = round(max(0.1, min(3.0, ls["intensity"] - dy * 0.1)), 2)
            self._dirty = True
            self._update_caption()
        elif self._tab == TAB_ROBOT:
            rs = self.arena["robot_start"]
            rs["heading_deg"] = (rs["heading_deg"] + dy * 5) % 360
            self._dirty = True
            self._update_caption()

    def _handle_key(self, key):
        # Confirm-done overlay
        if self._confirm_done:
            if key == pygame.K_ESCAPE:
                self._confirm_done = False
            return

        # Save As overlay
        if self._saveas_active:
            if key == pygame.K_RETURN:
                name = self._saveas_val.strip()
                if name:
                    if not name.endswith(".json"):
                        name += ".json"
                    base = os.path.dirname(self._arena_path) \
                           if self._arena_path else "."
                    path = os.path.join(base, name)
                    self._save(path)
                    if getattr(self, "_saveas_for_done", False):
                        self._saveas_for_done = False
                        self._running = False
                self._saveas_active = False
            elif key == pygame.K_ESCAPE:
                self._saveas_active = False
                self._saveas_for_done = False
            elif key == pygame.K_BACKSPACE:
                self._saveas_val = self._saveas_val[:-1]
            return

        # Arena tab field editing
        if self._focused:
            if key == pygame.K_RETURN:
                self._apply_arena_fields()
                self._focused = None
            elif key == pygame.K_ESCAPE:
                self._focused = None
                self._setup_arena_fields()
            elif key == pygame.K_BACKSPACE:
                self._fields[self._focused] = self._fields[self._focused][:-1]
            elif key == pygame.K_TAB:
                keys = list(self._fields.keys())
                idx = keys.index(self._focused)
                self._focused = keys[(idx+1) % len(keys)]
            return

        mods = pygame.key.get_mods()
        if key == pygame.K_z and (mods & pygame.KMOD_CTRL):
            self._redo() if (mods & pygame.KMOD_SHIFT) else self._undo()
        elif key == pygame.K_y and (mods & pygame.KMOD_CTRL):
            self._redo()
        elif key == pygame.K_s and (mods & pygame.KMOD_CTRL):
            self._save()
        elif key == pygame.K_ESCAPE:
            if self._wall_p0:
                self._wall_p0 = None
                self._status  = "Wall cancelled"
            else:
                self._deselect()
        elif key == pygame.K_DELETE:
            if self._sel_light is not None:
                self._push_undo()
                self.arena["light_sources"].pop(self._sel_light)
                self._sel_light = None
                self._dirty = True
                self._update_caption()
                self._status = "Light deleted"
            elif self._sel_wall is not None:
                self._push_undo()
                self.arena["internal_walls"].pop(self._sel_wall)
                self._sel_wall = None
                self._wall_p0  = None
                self._dirty = True
                self._update_caption()
                self._status = "Wall deleted"

    def _handle_text(self, text):
        if self._saveas_active:
            self._saveas_val += text
            return
        if self._focused:
            self._fields[self._focused] += text

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        clock = pygame.time.Clock()
        while self._running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._request_done()

                elif event.type == pygame.VIDEORESIZE:
                    self._ww = event.w
                    self._wh = event.h
                    self._screen = pygame.display.set_mode(
                        (self._ww, self._wh), pygame.RESIZABLE)

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self._handle_mousedown(event.pos, event.button)

                elif event.type == pygame.MOUSEMOTION:
                    self._handle_mousemotion(event.pos)

                elif event.type == pygame.MOUSEWHEEL:
                    self._handle_scroll(event.y, pygame.mouse.get_pos())

                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event.key)

                elif event.type == pygame.TEXTINPUT:
                    self._handle_text(event.text)

            self._draw()
            clock.tick(60)

        pygame.quit()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PAW Arena Builder")
    ap.add_argument("--arena", default=None,
                    help="Path to arena JSON file to load")
    args = ap.parse_args()
    ArenaBuilder(arena_path=args.arena).run()
