"""
valentinos/hub.py
------------------
Valentino's Vehicles — main hub.

Launched from the robosim game selector (or directly).
Owns the pygame window, layout, theme, Ray dialogue, and all game states.

States
------
  welcome          Ray intro + game menu
  byov_intro       Brief BYOV introduction with Ray
  byov_build       Wiring editor (full-window, returns here)
  byov_run         Simulation running
  byov_results     Post-run: replay trace, try again, change wiring
  ntv_placeholder  Name That Vehicle — coming soon panel
  haf_placeholder  Hunt and Forage — coming soon panel

Layout: left panel (controls/narrative) + right canvas (arena/art)
Theme:  inherits robosim theme selection
"""

from __future__ import annotations
import math
import os
import sys
import time
import subprocess
import datetime

ROOT         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)   # CloseTheGap/ — parent of valentinos/

# Insert project root so `import valentinos.engine` works regardless of cwd
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# Insert valentinos root for relative imports within the package
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Also add robosim so theme/professor can be imported
def _find_robosim() -> str | None:
    """Walk up from ROOT looking for a robosim package directory."""
    p = ROOT
    for _ in range(6):
        for candidate in ["robosim", "robosim_extracted/robosim"]:
            c = os.path.join(p, candidate)
            if os.path.exists(os.path.join(c, "robosim", "theme.py")):
                return c
        p = os.path.dirname(p)
    return None

_ROBOSIM = _find_robosim()
if _ROBOSIM and _ROBOSIM not in sys.path:
    sys.path.insert(0, _ROBOSIM)

import pygame

# ── Theme — use robosim theme if available, else inline fallback ────────────
try:
    import robosim.theme as T
    from robosim.theme import (
        draw_double_rule, draw_scanlines, draw_btn, draw_panel,
        font_hd, font_md, font_sm,
    )
    _HAS_THEME = True
except ImportError:
    try:
        sys.path.insert(0, os.path.join(ROOT, "shared"))
        import theme as T
        from theme import (
            draw_double_rule, draw_scanlines, draw_btn, draw_panel,
            font_hd, font_md, font_sm,
        )
        _HAS_THEME = True
    except ImportError:
        _HAS_THEME = False

# ── Layout ──────────────────────────────────────────────────────────────────
try:
    if _HAS_THEME:
        from robosim.layout import Layout
    else:
        raise ImportError
except ImportError:
    try:
        from shared.layout import Layout
    except ImportError:
        # Inline minimal layout fallback
        import pygame as _pg
        class Layout:
            def __init__(self, ww, wh):
                self.ww, self.wh = ww, wh
                self.panel_w = int(ww * 0.32)
                self.controls  = _pg.Rect(0, 0, self.panel_w, wh//2)
                self.narrative = _pg.Rect(0, wh//2, self.panel_w, wh//2)
                self.arena     = _pg.Rect(self.panel_w, 0, ww-self.panel_w, wh)
                self.panel     = _pg.Rect(0, 0, self.panel_w, wh)
            @property
            def ctrl_inner(self): return self.controls.inflate(-16,-16)
            @property
            def narr_inner(self): return self.narrative.inflate(-12,-12)
            @staticmethod
            def compute_window_size(frac=1.0):
                import sys
                info      = pygame.display.Info()
                taskbar_h = {"win32": 48, "darwin": 50}.get(sys.platform, 52)
                margin    = 8
                return (max(800, info.current_w - margin * 2),
                        max(500, info.current_h - taskbar_h - margin * 2))

# ── Professor Ray dialogue ──────────────────────────────────────────────────
try:
    from robosim.professor import DialogueBox, load_script
    _HAS_PROF = True
except ImportError:
    try:
        from shared.professor import DialogueBox, load_script
        _HAS_PROF = True
    except ImportError:
        _HAS_PROF = False
        class DialogueBox:
            def __init__(self, *a, **k): self.is_done = True
            def load(self, *a): pass
            def update(self, dt): pass
            def draw(self, *a): pass
            def advance(self): pass
            def skip(self): pass
        def load_script(folder, name, fallback=""):
            p = os.path.join(ROOT, "scripts", folder.lower(), f"{name}.txt")
            if os.path.exists(p):
                with open(p) as f: return f.read()
            return fallback

# ── Engine imports ──────────────────────────────────────────────────────────
from valentinos.engine.vehicle  import VehicleConfig, VehicleEvaluator, SensorReadings
from valentinos.engine.robot_body import (
    RobotState, ir_reading, ldr_reading, IR_CONFIGS, LDR_MOUNTS, SensorMount,
)
from valentinos.engine.recorder import Recorder
from valentinos.engine.signals  import Connection
from valentinos.arena.arena     import (
    load_arena, save_arena, draw_arena, ray_distance, light_at,
)

# ── Constants ───────────────────────────────────────────────────────────────
GAME_DIR   = os.path.join(ROOT, "games", "byov")
ARENA_PATH = os.path.join(GAME_DIR, "valentinos_arena.json")
REC_DIR    = os.path.join(GAME_DIR, "recordings")
PHYS_DT    = 1.0 / 120.0
ROBOT_R    = 0.047   # collision radius


# ── Hub ─────────────────────────────────────────────────────────────────────

class Hub:

    def __init__(self):
        self._state = "welcome"

        # Vehicle
        self._config = VehicleConfig(
            connections=[
                Connection("PL", "FL", "blue"),
                Connection("PR", "FR", "blue"),
            ],
            name="Default: Cowardice",
        )
        self._evaluator = VehicleEvaluator(self._config)

        # Arena
        self._arena = load_arena(ARENA_PATH)

        # Robot
        self._robot   = RobotState()
        self._reset_robot()
        self._running = False
        self._accum   = 0.0
        self._last_tick = 0.0
        self._signals_snap: dict = {}
        self._trace: list = []
        self._recorder = Recorder()

        # Pygame
        pygame.init()
        ww, wh = Layout.compute_window_size(0.90)
        self._layout = Layout(ww, wh)
        self._screen = pygame.display.set_mode((ww, wh))
        pygame.display.set_caption("Valentino's Vehicles")
        self._clock = pygame.time.Clock()

        global WW, WH
        WW, WH = ww, wh

        if _HAS_THEME:
            self._font_hd = font_hd()
            self._font_md = font_md()
            self._font_sm = font_sm()
        else:
            self._font_hd = pygame.font.SysFont("Courier New", 20)
            self._font_md = pygame.font.SysFont("Courier New", 16)
            self._font_sm = pygame.font.SysFont("Courier New", 13)

        # Dialogue
        lay = self._layout
        self._dlg = DialogueBox(lay.narr_inner.width,
                                lay.narr_inner.height,
                                T.CURRENT if _HAS_THEME else "phosphor",
                                font_size=13)
        self._load_intro()
        self._show_dlg = True

        self._ntv = None   # NTVGame instance when active
        self._exit_requested = False
        self._btn_rects: dict = {}
        self._status = ""

    # ── Intro ──────────────────────────────────────────────────────────────

    def _load_intro(self):
        text = load_script("ray", "vv_intro",
                           fallback="RAY: Welcome to Valentino's Vehicles!")
        self._dlg.load(text)

    def _load_byov_intro(self):
        text = load_script("ray", "byov_intro",
                           fallback="RAY: Build a vehicle and watch it run.")
        self._dlg.load(text)

    # ── Robot helpers ──────────────────────────────────────────────────────

    def _reset_robot(self):
        rs = self._arena.get("robot_start", {})
        self._robot = RobotState(
            x=rs.get("x", 0.0),
            y=rs.get("y", 0.0),
            heading=math.radians(rs.get("heading_deg", 90.0)),
        )
        self._evaluator.reset()
        self._trace = []
        self._signals_snap = {}

    def _read_sensors(self) -> SensorReadings:
        ir_m  = IR_CONFIGS["standard"]
        def ir(mount):
            wx, wy, wa = self._robot.sensor_world_pos(mount)
            return ir_reading(ray_distance(wx, wy, wa, self._arena, 0.5))
        def ldr(mount):
            wx, wy, _ = self._robot.sensor_world_pos(mount)
            illum = light_at(wx, wy, self._arena)
            illum = max(0.3, illum) if self._arena["light_sources"] else 0.3
            return ldr_reading(illum)
        return SensorReadings(
            RL=ir(ir_m[0]), RR=ir(ir_m[1]),
            PL=ldr(LDR_MOUNTS[0]), PR=ldr(LDR_MOUNTS[1]))

    def _tick(self, dt: float):
        sensors = self._read_sensors()
        motors  = self._evaluator.tick(sensors, dt)
        old_x, old_y = self._robot.x, self._robot.y
        self._robot.step(motors.left, motors.right, dt)

        # Collision — robot stops on contact, no sliding
        aw = self._arena["width"]  / 2 - ROBOT_R
        ah = self._arena["height"] / 2 - ROBOT_R
        boundary_hit = (self._robot.x < -aw or self._robot.x > aw or
                        self._robot.y < -ah or self._robot.y > ah)
        if boundary_hit:
            self._robot.x, self._robot.y = old_x, old_y

        # Internal walls
        for iw in self._arena.get("internal_walls", []):
            if self._circle_seg(self._robot.x, self._robot.y, ROBOT_R,
                                iw["x0"], iw["y0"], iw["x1"], iw["y1"]):
                self._robot.x, self._robot.y = old_x, old_y
                break

        self._signals_snap = self._evaluator.signal_snapshot()
        self._signals_snap["_left"]  = motors.left
        self._signals_snap["_right"] = motors.right

        self._trace.append((self._robot.x, self._robot.y))
        if len(self._trace) > 5000:
            self._trace = self._trace[-5000:]

        if self._recorder.is_active:
            self._recorder.record(self._robot, self._signals_snap, motors)

    @staticmethod
    def _circle_seg(cx, cy, r, ax, ay, bx, by) -> bool:
        dx, dy = bx-ax, by-ay
        lsq = dx*dx + dy*dy
        if lsq < 1e-12:
            return math.hypot(cx-ax, cy-ay) < r
        t = max(0.0, min(1.0, ((cx-ax)*dx+(cy-ay)*dy)/lsq))
        return math.hypot(cx-(ax+t*dx), cy-(ay+t*dy)) < r

    # ── Sim start/stop ─────────────────────────────────────────────────────

    def _start_run(self):
        self._running   = True
        self._last_tick = time.monotonic()
        self._accum     = 0.0
        os.makedirs(REC_DIR, exist_ok=True)
        self._recorder.start()
        self._status = "Running  —  press ■ Stop when done"

    def _stop_run(self):
        self._running = False
        if self._recorder.is_active:
            self._recorder.stop()
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path  = os.path.join(REC_DIR, f"run_{stamp}.vvrec")
            self._recorder.save(path)
        self._state  = "byov_results"
        self._status = "Run complete"

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(self):
        last_dlg_ms = pygame.time.get_ticks()

        while True:
            # Wall-clock dt (for NTV and dialogue, independent of sim running)
            _now_w  = time.monotonic()
            dt_wall = min(_now_w - getattr(self, "_wall_last", _now_w), 0.05)
            self._wall_last = _now_w

            # Physics
            if self._running:
                now = time.monotonic()
                dt  = min(now - self._last_tick, 0.05)
                self._last_tick = now
                self._accum    += dt
                while self._accum >= PHYS_DT:
                    self._tick(PHYS_DT)
                    self._accum -= PHYS_DT

            # NTV update (owns its own physics)
            if self._state == "ntv_active" and self._ntv:
                self._ntv.update(min(dt_wall, 0.05))
                if self._ntv.is_done:
                    self._ntv  = None
                    self._state = "welcome"
                    self._show_dlg = False

            # Dialogue tick
            now_ms = pygame.time.get_ticks()
            if self._show_dlg and not self._dlg.is_done:
                self._dlg.update((now_ms - last_dlg_ms) / 1000.0)
            last_dlg_ms = now_ms

            # Draw
            self._screen.fill(T.BG if _HAS_THEME else (10,12,10))
            self._btn_rects = {}
            if self._state == "ntv_active" and self._ntv:
                # NTV draws both canvas and panel itself
                self._draw_panel_background()
                self._ntv.draw(
                    self._screen,
                    self._layout.arena,
                    self._layout.ctrl_inner.x,
                    self._layout.ctrl_inner.width,
                    self._layout.narr_inner,
                    self._layout.ctrl_inner)
            else:
                self._draw_canvas()
                self._draw_panel()
            if _HAS_THEME and T.SCANLINES:
                draw_scanlines(self._screen,
                               pygame.Rect(0, 0, WW, WH), alpha=18)
            pygame.display.flip()

            # Events
            # Exit requested via button
            if self._exit_requested:
                pygame.quit()
                return

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    self._on_key(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self._on_click(event.pos, event.button)

            self._clock.tick(60)

    # ── Input ──────────────────────────────────────────────────────────────

    def _on_key(self, event):
        if self._state == "ntv_active" and self._ntv:
            self._ntv.handle_event(event)
            return
        if self._show_dlg and not self._dlg.is_done:
            if event.key == pygame.K_SPACE:
                self._dlg.advance()
            elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                self._dlg.skip()
            return
        if event.key == pygame.K_ESCAPE:
            if self._running:
                self._stop_run()
            elif self._state in ("byov_run", "byov_results"):
                self._state = "byov_intro"
            elif self._state.startswith("byov"):
                self._state = "welcome"

    def _on_click(self, pos, button):
        if button != 1:
            return
        if self._state == "ntv_active" and self._ntv:
            import pygame as _pg
            self._ntv.handle_event(
                _pg.event.Event(_pg.MOUSEBUTTONDOWN,
                                {"pos": pos, "button": button}))
            return
        # Dialogue advance
        if self._show_dlg and not self._dlg.is_done:
            nr = self._layout.narrative
            if nr.collidepoint(pos):
                self._dlg.advance()
                return
        # Buttons
        for name, rect in self._btn_rects.items():
            if rect.collidepoint(pos):
                self._handle_btn(name)
                return

    def _handle_btn(self, name: str):
        # ── Welcome ─────────────────────────────────────────────────────
        if name == "btn_byov":
            self._state = "byov_intro"
            self._load_byov_intro()
            self._show_dlg = True

        elif name == "btn_ntv":
            self._launch_ntv()

        elif name == "btn_haf":
            self._state = "haf_placeholder"
            self._show_dlg = False

        elif name == "btn_play_intro":
            self._load_intro()
            self._show_dlg = True

        # ── BYOV intro ──────────────────────────────────────────────────
        elif name == "btn_byov_continue":
            self._state    = "byov_build"
            self._show_dlg = False
            self._open_wiring_editor()

        # ── BYOV build ──────────────────────────────────────────────────
        elif name == "btn_edit_wiring":
            self._open_wiring_editor()

        elif name == "btn_edit_arena":
            self._open_arena_builder()

        elif name == "btn_run":
            if not self._running:
                self._state = "byov_run"
                self._reset_robot()
                self._start_run()

        # ── BYOV run ────────────────────────────────────────────────────
        elif name == "btn_stop":
            self._stop_run()

        # ── BYOV results ────────────────────────────────────────────────
        elif name == "btn_run_again":
            self._state = "byov_run"
            self._reset_robot()
            self._start_run()

        elif name == "btn_change_wiring":
            self._state = "byov_build"
            self._open_wiring_editor()

        elif name == "btn_change_arena":
            self._state = "byov_build"
            self._open_arena_builder()

        elif name == "btn_byov_menu":
            self._state    = "welcome"
            self._show_dlg = False

        elif name == "btn_exit_game":
            self._exit_requested = True

        # ── Placeholders ────────────────────────────────────────────────
        elif name == "btn_back":
            self._state    = "welcome"
            self._show_dlg = False

    # ── Wiring editor ──────────────────────────────────────────────────────

    # ── NTV launcher ───────────────────────────────────────────────────────

    def _launch_ntv(self):
        from valentinos.games.ntv.ntv_game import NTVGame
        self._ntv = NTVGame(
            dlg_class      = DialogueBox,
            load_script_fn = load_script,
            font_hd        = self._font_hd,
            font_md        = self._font_md,
            font_sm        = self._font_sm,
            has_theme      = _HAS_THEME,
            theme          = T if _HAS_THEME else None,
        )
        self._state    = "ntv_active"
        self._show_dlg = False

    def _open_wiring_editor(self):
        from valentinos.builder.wiring_editor import WiringEditor
        editor = WiringEditor(initial_config=self._config,
                              title="Edit Vehicle Wiring")
        result = editor.run()
        # Restore hub window
        self._screen = pygame.display.set_mode(
            (self._layout.ww, self._layout.wh))
        pygame.display.set_caption("Valentino's Vehicles")
        if _HAS_THEME:
            self._font_hd = font_hd()
            self._font_md = font_md()
            self._font_sm = font_sm()
        pygame.event.clear()

        if result is not None:
            self._config    = result
            self._evaluator = VehicleEvaluator(result)
            self._reset_robot()
        self._state = "byov_build"

    # ── Arena builder ──────────────────────────────────────────────────────

    def _open_arena_builder(self):
        save_arena(self._arena, ARENA_PATH)

        vv_root      = ROOT
        project_root = os.path.dirname(vv_root)
        candidates   = [
            os.path.join(project_root, "shared",
                         "tools", "arena_builder.py"),
            os.path.join(project_root, "robosim",
                         "tools", "arena_builder.py"),
            os.path.join(project_root, "robosim_extracted", "robosim",
                         "tools", "arena_builder.py"),
        ]
        env = os.environ.get("ARENA_BUILDER")
        if env and os.path.exists(env):
            candidates.insert(0, env)

        builder = next((c for c in candidates if os.path.exists(c)), None)

        if builder:
            robosim_root = os.path.dirname(os.path.dirname(builder))
            pygame.display.set_mode((1, 1))
            pygame.display.set_caption("")
            subprocess.run(
                [sys.executable, builder,
                 "--arena", os.path.abspath(ARENA_PATH)],
                cwd=robosim_root)
            pygame.init()
            self._screen = pygame.display.set_mode(
                (self._layout.ww, self._layout.wh))
            pygame.display.set_caption("Valentino's Vehicles")
            if _HAS_THEME:
                self._font_hd = font_hd()
                self._font_md = font_md()
                self._font_sm = font_sm()
            pygame.event.clear()
            self._arena = load_arena(ARENA_PATH)
            self._reset_robot()
        else:
            self._status = "Arena builder not found — edit arena JSON directly"
            print(f"[valentinos] Arena builder not found. Searched: {candidates}")

        self._state = "byov_build"

    # ── Drawing helpers ────────────────────────────────────────────────────

    def _btn(self, surf, x, y, w, h, label, name,
             accent=False, disabled=False, color=None):
        rect = pygame.Rect(x, y, w, h)
        self._btn_rects[name] = rect
        if _HAS_THEME:
            mx, my = pygame.mouse.get_pos()
            draw_btn(surf, rect, label, self._font_md,
                     active=accent, disabled=disabled,
                     hover=rect.collidepoint(mx, my) and not disabled,
                     color_override=color)
        else:
            mx, my = pygame.mouse.get_pos()
            hov  = rect.collidepoint(mx, my) and not disabled
            fill = color or ((30,160,50) if hov else (8,10,8))
            pygame.draw.rect(surf, fill, rect, border_radius=3)
            pygame.draw.rect(surf, (30,58,30), rect, 1, border_radius=3)
            t = self._font_md.render(label, True, (220,255,220))
            surf.blit(t, (rect.centerx - t.get_width()//2,
                          rect.centery - t.get_height()//2))

    def _rule(self, surf, y):
        if _HAS_THEME:
            draw_double_rule(surf, 0, y, self._layout.panel_w)
        else:
            pygame.draw.line(surf, (30,58,30), (0, y),
                             (self._layout.panel_w, y))

    def _text(self, surf, text, x, y, font=None, col=None, max_w=None):
        font = font or self._font_sm
        col  = col  or (T.TEXT if _HAS_THEME else (160,220,160))
        if max_w is None:
            surf.blit(font.render(text, True, col), (x, y))
            return y + font.get_linesize() + 2
        # Word-wrap
        words = text.split()
        line  = ""
        for w in words:
            test = (line + " " + w).strip()
            if font.size(test)[0] <= max_w:
                line = test
            else:
                if line:
                    surf.blit(font.render(line, True, col), (x, y))
                    y += font.get_linesize() + 2
                line = w
        if line:
            surf.blit(font.render(line, True, col), (x, y))
            y += font.get_linesize() + 2
        return y

    # ── Canvas ─────────────────────────────────────────────────────────────

    def _draw_canvas(self):
        cr    = self._layout.arena
        state = self._state

        if state in ("byov_run", "byov_results", "byov_build"):
            traces = {"robot": self._trace} if self._trace else None
            robots = [self._robot] if state in ("byov_run","byov_results") else None
            draw_arena(self._screen, cr, self._arena,
                       robot_states=robots, traces=traces,
                       font_sm=self._font_sm)
        elif state == "welcome":
            self._draw_welcome_art(cr)
        else:
            # Placeholder canvas — dark with centred label
            pygame.draw.rect(self._screen,
                             T.BG if _HAS_THEME else (10,12,10), cr)
            lbl = self._font_hd.render("COMING SOON", True,
                                       T.BORDER if _HAS_THEME else (30,58,30))
            self._screen.blit(lbl, (cr.centerx - lbl.get_width()//2,
                                    cr.centery - lbl.get_height()//2))

    def _draw_welcome_art(self, cr):
        """Decorative canvas for welcome state — animated vehicle silhouette."""
        pygame.draw.rect(self._screen,
                         T.BG if _HAS_THEME else (10,12,10), cr)
        col  = T.BORDER if _HAS_THEME else (30,58,30)
        col2 = T.PHOSPHOR_DIM if _HAS_THEME else (20,90,30)
        cx, cy = cr.centerx, cr.centery

        # Schematic-style robot silhouette
        bw, bh = 120, 80
        body = pygame.Rect(cx - bw//2, cy - bh//2, bw, bh)
        pygame.draw.rect(self._screen, col, body, 2, border_radius=6)

        # Wheels
        for wx, wy in [(cx - bw//2 - 14, cy - 22),
                       (cx - bw//2 - 14, cy + 6),
                       (cx + bw//2 - 4,  cy - 22),
                       (cx + bw//2 - 4,  cy + 6)]:
            pygame.draw.rect(self._screen, col,
                             pygame.Rect(wx, wy, 18, 16), 1, border_radius=2)

        # Sensor dots (front = right of body in this orientation)
        for sy in [cy - 22, cy + 6]:
            pygame.draw.circle(self._screen, col2,
                               (cx + bw//2 + 18, sy + 8), 5, 1)

        # Signal lines (stylised wiring)
        for start, end in [
            ((cx + bw//2 + 18, cy - 14), (cx - bw//2 - 6, cy - 14)),
            ((cx + bw//2 + 18, cy + 14), (cx - bw//2 - 6, cy + 14)),
        ]:
            pygame.draw.line(self._screen, col2, start, end, 1)

        # Title text on canvas
        title = self._font_hd.render("VALENTINO'S VEHICLES",
                                     True,
                                     T.PHOSPHOR_DIM if _HAS_THEME
                                     else (20,90,30))
        self._screen.blit(title,
                          (cx - title.get_width()//2, cy - bh//2 - 52))
        sub = self._font_sm.render(
            "named for Valentino Braitenberg  (1926–2011)",
            True, T.BORDER if _HAS_THEME else (30,58,30))
        self._screen.blit(sub,
                          (cx - sub.get_width()//2, cy + bh//2 + 18))

    # ── Panel ──────────────────────────────────────────────────────────────

    def _draw_panel_background(self):
        """Draw panel bg and border only — used when NTV owns the panel content."""
        lay = self._layout
        BG2 = T.PANEL      if _HAS_THEME else (13,15,13)
        BRD = T.BORDER     if _HAS_THEME else (30,58,30)
        WG  = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        pygame.draw.rect(self._screen, BG2, lay.panel)
        pygame.draw.line(self._screen, BRD,
                         (lay.panel.right-2, 0), (lay.panel.right-2, lay.wh))
        pygame.draw.line(self._screen, WG,
                         (lay.panel.right-1, 0), (lay.panel.right-1, lay.wh))

    def _draw_panel(self):
        lay = self._layout
        BG2 = T.PANEL      if _HAS_THEME else (13,15,13)
        DPL = T.PANEL_DEEP if _HAS_THEME else (8,10,8)
        BRD = T.BORDER     if _HAS_THEME else (30,58,30)
        WG  = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        TXT = T.TEXT        if _HAS_THEME else (160,220,160)
        DIM = T.TEXT_DIM    if _HAS_THEME else (70,110,70)

        # Panel background
        pygame.draw.rect(self._screen, BG2, lay.panel)
        pygame.draw.line(self._screen, BRD,
                         (lay.panel.right-2, 0),
                         (lay.panel.right-2, lay.wh))
        pygame.draw.line(self._screen, WG,
                         (lay.panel.right-1, 0),
                         (lay.panel.right-1, lay.wh))

        # Controls region
        x = lay.ctrl_inner.x
        w = lay.ctrl_inner.width
        self._dispatch_controls(x, w)

        # Divider
        self._rule(self._screen, lay.narrative.top - 2)

        # Narrative region
        pygame.draw.rect(self._screen, DPL, lay.narrative)
        self._draw_narrative()

    def _dispatch_controls(self, x, w):
        state = self._state
        if state == "welcome":
            self._draw_ctrl_welcome(x, w)
        elif state == "byov_intro":
            self._draw_ctrl_byov_intro(x, w)
        elif state == "byov_build":
            self._draw_ctrl_byov_build(x, w)
        elif state == "byov_run":
            self._draw_ctrl_byov_run(x, w)
        elif state == "byov_results":
            self._draw_ctrl_byov_results(x, w)
        elif state == "ntv_active":
            if self._ntv:
                self._ntv.draw(
                    self._screen,
                    self._layout.arena,
                    self._layout.ctrl_inner.x,
                    self._layout.ctrl_inner.width,
                    self._layout.narr_inner,
                    self._layout.ctrl_inner)
        elif state == "haf_placeholder":
            self._draw_ctrl_placeholder(x, w, "HUNT AND FORAGE")

    # ── Control panels ─────────────────────────────────────────────────────

    def _draw_ctrl_welcome(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("VALENTINO'S", True,
                                  T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt, (x, y)); y += 26
        tt2 = self._font_hd.render("VEHICLES", True,
                                   T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14

        sub = self._font_sm.render("Select a game:", True,
                                   T.TEXT_DIM if _HAS_THEME else (70,110,70))
        self._screen.blit(sub, (x, y)); y += 20

        games = [
            ("Build Your Own Vehicle", "btn_byov", True),
            ("Name That Vehicle",      "btn_ntv",  True),
            ("Hunt and Forage",        "btn_haf",  False),
        ]
        for label, name, avail in games:
            col = (T.PHOSPHOR_MID if _HAS_THEME else (30,160,50)) if avail else None
            self._btn(self._screen, x, y, w, 38, label, name,
                      accent=avail, disabled=not avail, color=col)
            if not avail:
                soon = self._font_sm.render("coming soon", True,
                                            T.TEXT_DIM if _HAS_THEME
                                            else (70,110,70))
                self._screen.blit(
                    soon, (x + w - soon.get_width(), y + 12))
            y += 48

        # Exit Game — bottom of welcome panel
        exit_y = lay.controls.bottom - 34
        self._btn(self._screen, x, exit_y, w, 28,
                  "Exit Game", "btn_exit_game")

    def _draw_ctrl_byov_intro(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("BUILD YOUR OWN", True,
                                  T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt, (x, y)); y += 26
        tt2 = self._font_hd.render("VEHICLE", True,
                                   T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14

        desc = ("Connect sensors to motors. Add neurons to shape "
                "signals. Watch what emerges.")
        y = self._text(self._screen, desc, x, y,
                       max_w=w,
                       col=T.TEXT if _HAS_THEME else (160,220,160))
        y += 8

        # Continue anchored to bottom of controls
        btn_y = lay.controls.bottom - 48
        self._btn(self._screen, x, btn_y, w, 38,
                  "Open Wiring Editor  →", "btn_byov_continue", accent=True)

    def _draw_ctrl_byov_build(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("YOUR VEHICLE", True,
                                  T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt, (x, y)); y += 30
        self._rule(self._screen, y); y += 12

        # Connection summary
        nc = len(self._config.connections)
        ct = self._font_sm.render(
            f"{nc} connection{'s' if nc != 1 else ''}",
            True, T.PHOSPHOR if _HAS_THEME else (51,255,87))
        self._screen.blit(ct, (x, y)); y += 18

        for conn in self._config.connections[:6]:
            lbl = self._font_sm.render(
                f"  {conn.source} → {conn.dest}  ({conn.color})",
                True, T.TEXT_DIM if _HAS_THEME else (70,110,70))
            self._screen.blit(lbl, (x, y)); y += 15
        if nc > 6:
            more = self._font_sm.render(f"  … and {nc-6} more", True,
                                        T.TEXT_DIM if _HAS_THEME
                                        else (70,110,70))
            self._screen.blit(more, (x, y)); y += 15

        y += 8
        self._rule(self._screen, y); y += 12

        self._btn(self._screen, x, y, w, 34,
                  "Edit Wiring", "btn_edit_wiring")
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "Edit Arena",  "btn_edit_arena")
        y += 44

        # Run button at bottom
        btn_y = lay.controls.bottom - 48
        self._btn(self._screen, x, btn_y, w, 38,
                  "▶  Run", "btn_run", accent=True)

    def _draw_meters(self, surf, x, y, w, sigs, config):
        """
        Draw M1 (left), M2 (centre), M3 (right) as vertical 10-segment
        LED bars filling bottom-to-top. All three always shown;
        unwired meters stay dim. M1/M3 = red, M2 = white.
        Returns updated y position below the meter display.
        """
        from valentinos.engine.signals import WIRE_WEIGHT
        SEGMENTS = 10
        LED_LIT  = {"M1": (220,50,50), "M2": (240,240,240), "M3": (220,50,50)}
        LED_DIM  = {"M1": (60,10,10),  "M2": (60,60,60),    "M3": (60,10,10)}
        DIM_COL  = T.TEXT_DIM if _HAS_THEME else (70,110,70)

        hdr = self._font_sm.render("METERS", True, DIM_COL)
        surf.blit(hdr, (x, y)); y += 14

        gap    = 6
        bar_w  = (w - gap * 2) // 3
        seg_h  = 12
        seg_gap = 2
        bar_h  = SEGMENTS * (seg_h + seg_gap) - seg_gap

        for mi, meter in enumerate(("M1", "M2", "M3")):
            val = 0.0
            for c in config.connections:
                if c.dest == meter:
                    val += sigs.get(c.source, 0.0) * WIRE_WEIGHT[c.color]
            val = max(0.0, min(1.0, val))
            lit_segs = int(val * SEGMENTS)
            mx = x + mi * (bar_w + gap)
            for seg in range(SEGMENTS):
                seg_y = y + bar_h - seg * (seg_h + seg_gap) - seg_h
                col   = LED_LIT[meter] if seg < lit_segs else LED_DIM[meter]
                pygame.draw.rect(surf, col,
                                 pygame.Rect(mx, seg_y, bar_w, seg_h),
                                 border_radius=2)
            lbl = self._font_sm.render(meter, True, DIM_COL)
            surf.blit(lbl, (mx + bar_w//2 - lbl.get_width()//2,
                            y + bar_h + 3))

        return y + bar_h + self._font_sm.get_linesize() + 8

    def _draw_ctrl_byov_run(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("RUNNING", True,
                                  T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt, (x, y)); y += 30
        self._rule(self._screen, y); y += 14

        # Meter display — always show all three, unwired stay dim
        if self._signals_snap:
            y = self._draw_meters(self._screen, x, y, w,
                                  self._signals_snap, self._config)

        # Stop at bottom
        btn_y = lay.controls.bottom - 48
        self._btn(self._screen, x, btn_y, w, 38,
                  "■  Stop", "btn_stop",
                  color=T.AMBER if _HAS_THEME else (255,149,0))

    def _draw_ctrl_byov_results(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("RUN COMPLETE", True,
                                  T.WHITE_GREEN if _HAS_THEME else (220,255,220))
        self._screen.blit(tt, (x, y)); y += 30
        self._rule(self._screen, y); y += 14

        note = self._font_sm.render("Trace preserved on canvas.",
                                    True,
                                    T.TEXT_DIM if _HAS_THEME else (70,110,70))
        self._screen.blit(note, (x, y)); y += 22

        self._btn(self._screen, x, y, w, 34,
                  "▶  Run Again",    "btn_run_again", accent=True)
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "Edit Wiring",     "btn_change_wiring")
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "Edit Arena",      "btn_change_arena")
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "← Menu",         "btn_byov_menu")

    def _draw_ctrl_placeholder(self, x, w, title: str):
        lay = self._layout
        y   = lay.ctrl_inner.y

        for line in title.split():
            tt = self._font_hd.render(line, True,
                                      T.WHITE_GREEN if _HAS_THEME
                                      else (220,255,220))
            self._screen.blit(tt, (x, y)); y += 26
        y += 4
        self._rule(self._screen, y); y += 14

        msg = ("This game is in development. "
               "Check back in a future release.")
        y = self._text(self._screen, msg, x, y, max_w=w,
                       col=T.TEXT_DIM if _HAS_THEME else (70,110,70))

        btn_y = lay.controls.bottom - 48
        self._btn(self._screen, x, btn_y, w, 38,
                  "← Menu",         "btn_back")

    # ── Narrative ──────────────────────────────────────────────────────────

    def _draw_narrative(self):
        lay  = self._layout
        nr   = lay.narr_inner

        if self._show_dlg and not self._dlg.is_done:
            self._dlg._w = nr.width
            self._dlg._h = nr.height
            self._dlg.draw(self._screen, nr.x, nr.y)
        else:
            # Play Intro link
            ir = pygame.Rect(nr.x, nr.bottom - 26, 110, 22)
            self._btn_rects["btn_play_intro"] = ir
            mx, my = pygame.mouse.get_pos()
            hov = ir.collidepoint(mx, my)
            DPL = T.PANEL_DEEP if _HAS_THEME else (8,10,8)
            BRD = T.BORDER     if _HAS_THEME else (30,58,30)
            DIM = T.TEXT_DIM   if _HAS_THEME else (70,110,70)
            pygame.draw.rect(self._screen,
                             T.PANEL if (hov and _HAS_THEME) else DPL,
                             ir, border_radius=3)
            pygame.draw.rect(self._screen, BRD, ir, 1, border_radius=3)
            it = self._font_sm.render("Play Intro", True, DIM)
            self._screen.blit(it,
                              (ir.centerx - it.get_width()//2,
                               ir.centery - it.get_height()//2))


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    if _HAS_THEME:
        T.apply(T.load_saved_theme())
    Hub().run()


if __name__ == "__main__":
    main()
