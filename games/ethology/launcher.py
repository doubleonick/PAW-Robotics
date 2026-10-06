"""
games/ethology/launcher.py
---------------------------
Robot Ethology game launcher.

Manages sketch, arena, robot file selection and simulation options.
Launches arena builder, simulation, and playback from one place.
Settings saved to games/ethology/.launcher_state.json.
"""

import datetime
import glob
import json
import os
import subprocess
import sys

# Ensure robosim package is importable
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_DIR       = os.path.dirname(os.path.abspath(__file__))
ARENAS_DIR     = os.path.join(GAME_DIR, "arenas")
_DEFAULT_ARENA = os.path.join(ARENAS_DIR, "arena_default.json")
_SESSION_ARENA = os.path.join(ARENAS_DIR, "session_current.json")
TOOLS_DIR        = os.path.join(ROOT, "tools")
SHARED_TOOLS_DIR = os.path.join(ROOT, "tools")
STATE_FILE = os.path.join(GAME_DIR, ".launcher_state.json")

sys.path.insert(0, ROOT)

import pygame

# ── Colours ───────────────────────────────────────────────────────────────────
C_BG        = (14,  16,  22)
C_PANEL     = (22,  25,  34)
C_EDGE      = (40,  45,  62)
C_TEXT      = (200, 210, 230)
C_TEXT_DIM  = ( 90, 100, 125)
C_HEADING   = (255, 215,  70)
C_ACCENT    = ( 70, 165, 255)
C_BTN       = ( 32,  38,  55)
C_BTN_HOV   = ( 48,  58,  82)
C_BTN_ACT   = ( 50, 130, 210)
C_BTN_DIS   = ( 28,  32,  44)
C_OK        = ( 80, 200, 120)
C_ERR       = (210,  70,  70)
C_TOGGLE_ON = ( 60, 190, 110)

WW, WH = 760, 580

# ── State ─────────────────────────────────────────────────────────────────────

DEFAULT_STATE = {
    "sketch":  "sketches/ldr_ethology.ino",
    "arena":   None,
    "robot":   "robot.json",
    "hud":     False,
    "ir_only": False,
    "scale":   "",
}


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
            for k, v in DEFAULT_STATE.items():
                s.setdefault(k, v)
            return s
        except Exception:
            pass
    return dict(DEFAULT_STATE)


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


# ── Launcher ──────────────────────────────────────────────────────────────────

def _active_arena():
    """Return the active arena path: session > default > legacy."""
    for p in (_SESSION_ARENA, _DEFAULT_ARENA,
              os.path.join(GAME_DIR, "ethology_arena.json")):
        if os.path.exists(p):
            return p
    return _DEFAULT_ARENA

class EthologyLauncher:

    def __init__(self):
        self.state       = load_state()
        self._status     = ""
        self._status_col = C_TEXT_DIM
        self._btn_rects  = {}
        self._focused    = None

        pygame.init()
        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")

        self._font_hd = pygame.font.SysFont("consolas", 28)
        self._font_md = pygame.font.SysFont("consolas", 16)
        self._font_sm = pygame.font.SysFont("consolas", 13)
        self._clock   = pygame.time.Clock()

    def _set_status(self, msg, ok=True):
        self._status     = msg
        self._status_col = C_OK if ok else C_ERR

    # ── Drawing helpers ───────────────────────────────────────────────────────

    def _btn(self, surf, rect, label, name,
             disabled=False, accent=False):
        self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx, my) and not disabled
        if disabled:
            col = C_BTN_DIS
        else:
            col = C_BTN_ACT if (hov and accent) else \
                  C_BTN_HOV if hov else \
                  C_BTN_ACT if accent else C_BTN
        pygame.draw.rect(surf, col, rect, border_radius=6)
        pygame.draw.rect(surf, C_EDGE if not disabled else (30,33,46),
                         rect, 1, border_radius=6)
        t_col = C_TEXT_DIM if disabled else \
                (C_HEADING if accent else C_TEXT)
        t = self._font_md.render(label, True, t_col)
        surf.blit(t, (rect.centerx - t.get_width()//2,
                      rect.centery - t.get_height()//2))

    def _toggle(self, surf, rect, label, key, name):
        self._btn_rects[name] = rect
        val = self.state.get(key, False)
        mx, my = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx, my)
        bg  = C_TOGGLE_ON if val else (C_BTN_HOV if hov else C_BTN)
        pygame.draw.rect(surf, bg,     rect, border_radius=6)
        pygame.draw.rect(surf, C_EDGE, rect, 1, border_radius=6)
        icon = "● " if val else "○ "
        t = self._font_md.render(icon + label, True,
                                 C_TEXT if val else C_TEXT_DIM)
        surf.blit(t, (rect.centerx - t.get_width()//2,
                      rect.centery - t.get_height()//2))

    def _field(self, surf, rect, key, name):
        self._btn_rects[name] = rect
        focused = self._focused == name
        bg  = (40, 48, 70) if focused else (28, 33, 48)
        brd = C_ACCENT if focused else C_EDGE
        pygame.draw.rect(surf, bg,  rect, border_radius=4)
        pygame.draw.rect(surf, brd, rect, 1, border_radius=4)
        val = str(self.state.get(key, ""))
        vt  = self._font_md.render(val, True, C_TEXT)
        surf.blit(vt, (rect.x + 6, rect.y + 6))

    def _file_row(self, surf, y, label, key, name_field,
                  name_browse, x0, w):
        lt = self._font_sm.render(label, True, C_TEXT_DIM)
        surf.blit(lt, (30, y + 7))
        self._field(surf, pygame.Rect(x0, y, w, 30), key, name_field)
        self._btn(surf, pygame.Rect(x0 + w + 8, y, 80, 30),
                  "Browse", name_browse)
        return y + 42

    def _section(self, surf, x, y, w, h, title):
        pygame.draw.rect(surf, C_PANEL,
                         pygame.Rect(x, y, w, h), border_radius=8)
        pygame.draw.rect(surf, C_EDGE,
                         pygame.Rect(x, y, w, h), 1, border_radius=8)
        tt = self._font_md.render(title, True, C_HEADING)
        surf.blit(tt, (x + 14, y + 10))
        return y + 36

    # ── Main draw ─────────────────────────────────────────────────────────────

    def _draw(self):
        surf = self._screen
        surf.fill(C_BG)
        self._btn_rects = {}
        pad = 18

        # Title
        t1 = self._font_hd.render("Robot Ethology", True, C_HEADING)
        t2 = self._font_sm.render("RoboSim", True, C_TEXT_DIM)
        surf.blit(t1, (pad, 14))
        surf.blit(t2, (pad, 46))
        pygame.draw.line(surf, C_EDGE, (0, 66), (WW, 66), 1)

        lx, ly, lw = pad, 80, 220

        # Workflow section
        cy = self._section(surf, lx, ly, lw, 322, "Workflow")

        self._btn(surf, pygame.Rect(lx+10, cy, lw-20, 46),
                  "⬡  Build Arena",    "btn_arena", accent=True)
        cy += 54
        self._btn(surf, pygame.Rect(lx+10, cy, lw-20, 46),
                  "⚙  Build Hierarchy","btn_hier",  accent=True)
        cy += 54
        self._btn(surf, pygame.Rect(lx+10, cy, lw-20, 46),
                  "▶  Run Simulation", "btn_run",   accent=True)
        cy += 54

        # Rec button
        rec_r = pygame.Rect(lx+10, cy, lw-20, 46)
        self._btn_rects["btn_rec"] = rec_r
        mx, my = pygame.mouse.get_pos()
        pygame.draw.rect(surf,
                         C_BTN_HOV if rec_r.collidepoint(mx,my) else C_BTN,
                         rec_r, border_radius=6)
        pygame.draw.rect(surf, C_EDGE, rec_r, 1, border_radius=6)
        pygame.draw.circle(surf, (220, 50, 50),
                           (rec_r.left + 22, rec_r.centery), 10)
        pygame.draw.circle(surf, (255, 80, 80),
                           (rec_r.left + 22, rec_r.centery), 10, 2)
        rt = self._font_md.render("Rec", True, C_TEXT)
        surf.blit(rt, (rec_r.left + 38,
                       rec_r.centery - rt.get_height()//2))
        cy += 54

        # Play button
        play_r = pygame.Rect(lx+10, cy, lw-20, 46)
        self._btn_rects["btn_play"] = play_r
        pygame.draw.rect(surf,
                         C_BTN_HOV if play_r.collidepoint(mx,my) else C_BTN,
                         play_r, border_radius=6)
        pygame.draw.rect(surf, C_EDGE, play_r, 1, border_radius=6)
        ic = (play_r.left + 22, play_r.centery)
        pygame.draw.rect(surf, C_TEXT_DIM,
                         pygame.Rect(ic[0]-10, ic[1]-10, 20, 20), 2,
                         border_radius=2)
        pygame.draw.polygon(surf, C_TEXT, [
            (ic[0]-4, ic[1]-6), (ic[0]-4, ic[1]+6), (ic[0]+7, ic[1])])
        pt = self._font_md.render("Play", True, C_TEXT)
        surf.blit(pt, (play_r.left + 38,
                       play_r.centery - pt.get_height()//2))

        # Right column
        rx  = lx + lw + pad
        rw  = WW - rx - pad

        # Files
        fy = self._section(surf, rx, ly, rw, 178, "Files")
        fy = self._file_row(surf, fy, "Sketch:", "sketch",
                            "fld_sketch", "brw_sketch",
                            x0=rx+110, w=rw-210)
        fy = self._file_row(surf, fy, "Arena:",  "arena",
                            "fld_arena",  "brw_arena",
                            x0=rx+110, w=rw-210)
        fy = self._file_row(surf, fy, "Robot:",  "robot",
                            "fld_robot",  "brw_robot",
                            x0=rx+110, w=rw-210)

        # Options
        oy = ly + 188
        oc = self._section(surf, rx, oy, rw, 130, "Options")
        tw = 130
        self._toggle(surf, pygame.Rect(rx+10,        oc, tw, 30),
                     "HUD",     "hud",     "tog_hud")
        self._toggle(surf, pygame.Rect(rx+10+tw+8,   oc, tw, 30),
                     "IR Only", "ir_only", "tog_ir")
        sc_y = oc + 42
        lt   = self._font_sm.render("Scale (px/m):", True, C_TEXT_DIM)
        surf.blit(lt, (rx+10, sc_y + 7))
        self._field(surf, pygame.Rect(rx+140, sc_y, 100, 30),
                    "scale", "fld_scale")
        lt2 = self._font_sm.render("leave blank = auto", True, C_TEXT_DIM)
        surf.blit(lt2, (rx+250, sc_y + 7))

        # Status bar
        pygame.draw.line(surf, C_EDGE, (0, WH-38), (WW, WH-38), 1)
        if self._status:
            st = self._font_sm.render(self._status, True, self._status_col)
            surf.blit(st, (pad, WH - 26))

        # Back hint
        bk = self._font_sm.render("Esc = game menu", True, C_TEXT_DIM)
        surf.blit(bk, (WW - bk.get_width() - pad, WH - 26))

        pygame.display.flip()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _list_files(self, pattern):
        matches = glob.glob(os.path.join(GAME_DIR, pattern))
        return sorted(os.path.relpath(m, GAME_DIR).replace("\\", "/")
                      for m in matches)

    def _browse(self, pattern, key):
        files = self._list_files(pattern)
        if not files:
            self._set_status(f"No files: {pattern}", ok=False)
            return
        cur = self.state.get(key, "")
        try:
            idx = files.index(cur)
            nxt = files[(idx + 1) % len(files)]
        except ValueError:
            nxt = files[0]
        self.state[key] = nxt
        save_state(self.state)
        self._set_status(f"Selected: {nxt}")

    def _launch(self, script, extra_args=None):
        save_state(self.state)
        pygame.display.set_mode((1, 1))
        pygame.display.set_caption("")
        cmd = [sys.executable, script] + (extra_args or [])
        try:
            subprocess.run(cmd, cwd=ROOT)
        except Exception as e:
            self._set_status(f"Launch failed: {e}", ok=False)
        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")
        pygame.event.clear()
        self._set_status("Returned to launcher")

    def _run_sim(self, record=False):
        args = [
            os.path.join(ROOT, "main.py"),
            "--sketch", os.path.join(GAME_DIR, self.state["sketch"]),
            "--arena",  _active_arena(),
            "--robot",  os.path.join(GAME_DIR, self.state["robot"]),
        ]
        if self.state.get("hud"):     args.append("--hud")
        if self.state.get("ir_only"): args.append("--ir-only")
        scale = self.state.get("scale", "").strip()
        if scale: args += ["--scale", scale]
        if record:
            rec_dir  = os.path.join(GAME_DIR, "recordings")
            os.makedirs(rec_dir, exist_ok=True)
            stamp    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            args    += ["--record",
                        os.path.join(rec_dir, f"run_{stamp}.robrec")]
        self._launch(args[0], args[1:])

    def _run_hierarchy_builder(self):
        self._launch(
            os.path.join(GAME_DIR, "hierarchy_builder.py")
        )

    def _run_arena_builder(self):
        self._launch(
            os.path.join(SHARED_TOOLS_DIR, "arena_builder.py"),
            ["--arena", _active_arena()]
        )

    def _run_playback(self):
        rec_dir = os.path.join(GAME_DIR, "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        self._launch(
            os.path.join(TOOLS_DIR, "playback.py"),
            [_active_arena(),
             "--recordings", rec_dir]
        )

    def _handle_btn(self, name):
        if   name == "btn_run":     self._run_sim()
        elif name == "btn_rec":     self._run_sim(record=True)
        elif name == "btn_play":    self._run_playback()
        elif name == "btn_arena":   self._run_arena_builder()
        elif name == "btn_hier":    self._run_hierarchy_builder()
        elif name == "brw_sketch":  self._browse("sketches/*.ino", "sketch")
        elif name == "brw_arena":   self._browse("*.json", "arena")
        elif name == "brw_robot":   self._browse("robot.json", "robot")
        elif name == "tog_hud":
            self.state["hud"] = not self.state.get("hud", False)
            save_state(self.state)
        elif name == "tog_ir":
            self.state["ir_only"] = not self.state.get("ir_only", False)
            save_state(self.state)

    def _handle_key(self, key):
        if self._focused == "fld_scale":
            val = str(self.state.get("scale", ""))
            if key == pygame.K_BACKSPACE:
                self.state["scale"] = val[:-1]
            elif key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_TAB):
                self._focused = None
                save_state(self.state)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            self._draw()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self._handle_key(event.key)
                elif event.type == pygame.TEXTINPUT:
                    if self._focused == "fld_scale" and \
                            event.text in "0123456789.":
                        self.state["scale"] = \
                            str(self.state.get("scale", "")) + event.text
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    clicked = False
                    for name, rect in self._btn_rects.items():
                        if rect.collidepoint(event.pos):
                            if name.startswith("fld_"):
                                self._focused = name
                            else:
                                self._focused = None
                                self._handle_btn(name)
                            clicked = True
                            break
                    if not clicked:
                        self._focused = None
            self._clock.tick(30)

        save_state(self.state)
        pygame.quit()


if __name__ == "__main__":
    EthologyLauncher().run()
