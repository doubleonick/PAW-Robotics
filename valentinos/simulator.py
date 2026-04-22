"""
valentinos/simulator.py
------------------------
Simulation window for Valentino's Vehicles.

Layout:
  Left panel  : controls + status
  Right canvas: arena with live robot

Panel buttons (always):
  ▶ Run / ■ Stop   — start or halt the simulation
  Edit Wiring      — pause sim, open wiring editor, resume
  Edit Arena       — pause sim, open arena builder, resume

The simulator owns the physics loop, sensor reads, and recording.
It takes a VehicleConfig and arena dict, both of which can be swapped
live via the Edit buttons.

Usage (standalone):
    python simulator.py
"""

from __future__ import annotations
import math
import os
import sys
import subprocess
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from valentinos.engine.vehicle  import VehicleConfig, VehicleEvaluator, SensorReadings
from valentinos.engine.robot_body import (
    RobotState, ir_reading, ldr_reading,
    IR_CONFIGS, LDR_MOUNTS, SensorMount,
)
from valentinos.engine.recorder import Recorder
from valentinos.arena.arena     import (
    load_arena, save_arena, draw_arena,
    ray_distance, light_at, DEFAULT_ARENA,
)
from valentinos.engine.signals  import Connection

# ── Palette ────────────────────────────────────────────────────────────────────

BG           = (10,  12,  10)
PANEL_COL    = (13,  15,  13)
PANEL_DEEP   = ( 8,  10,   8)
BORDER       = (30,  58,  30)
TEXT         = (160, 220, 160)
TEXT_DIM     = ( 70, 110,  70)
TEXT_BRIGHT  = (220, 255, 220)
PHOSPHOR     = ( 51, 255,  87)
PHOSPHOR_MID = ( 30, 160,  50)
PHOSPHOR_DIM = ( 20,  90,  30)
AMBER        = (255, 149,   0)
WHITE_GREEN  = (220, 255, 220)
RED_PH       = (255,  60,  60)
BLUE_PH      = ( 60, 160, 255)

PANEL_W  = 280
MARGIN   = 28
PHYS_DT  = 1.0 / 120.0
RENDER_DT = 1.0 / 30.0


# ── Default files ──────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.abspath(__file__))
ARENA_PATH = os.path.join(ROOT, "games", "byov", "valentinos_arena.json")
REC_DIR    = os.path.join(ROOT, "recordings")


# ── Simulator ──────────────────────────────────────────────────────────────────

class Simulator:

    def __init__(self, config: VehicleConfig,
                 arena: dict | None     = None,
                 arena_path: str        = ARENA_PATH,
                 ir_config: str         = "standard"):
        self._config     = config
        self._arena      = arena or load_arena(arena_path)
        self._arena_path = arena_path
        self._ir_config  = ir_config

        self._evaluator  = VehicleEvaluator(config)
        self._state      = RobotState()
        self._reset_robot()

        self._running    = False        # simulation ticking
        self._accum      = 0.0
        self._render_acc = 0.0
        self._last_tick  = 0.0

        self._recorder   = Recorder()
        self._trace: list[tuple[float,float]] = []   # path for drawing

        self._signals_snap: dict = {}   # last signal snapshot for HUD

        # Pygame init
        pygame.init()
        info      = pygame.display.Info()
        import sys as _sys
        taskbar_h = {"win32": 48, "darwin": 50}.get(_sys.platform, 52)
        ww = max(800, info.current_w  - 8 * 2)
        wh = max(500, info.current_h  - taskbar_h - 8 * 2)
        self._screen = pygame.display.set_mode((ww, wh))
        self._ww = ww   # saved for window restore after subprocesses
        self._wh = wh
        pygame.display.set_caption("Valentino's Vehicles — Simulator")
        self._clock  = pygame.time.Clock()

        self._font_hd = self._font(19)
        self._font_md = self._font(15)
        self._font_sm = self._font(13)

        self._btn_rects: dict[str, pygame.Rect] = {}
        self._status = "Ready — press Run to start"

    # ── Fonts ──────────────────────────────────────────────────────────────

    def _font(self, size):
        for name in ("Courier New", "Courier", "monospace"):
            try:
                f = pygame.font.SysFont(name, size)
                if f:
                    return f
            except Exception:
                pass
        return pygame.font.Font(None, size)

    # ── Robot reset ────────────────────────────────────────────────────────

    def _reset_robot(self):
        rs = self._arena.get("robot_start", {})
        self._state = RobotState(
            x       = rs.get("x", 0.0),
            y       = rs.get("y", 0.0),
            heading = math.radians(rs.get("heading_deg", 90.0)),
        )
        self._evaluator.reset()
        self._trace = []

    # ── Sensor reads ───────────────────────────────────────────────────────

    def _read_sensors(self) -> SensorReadings:
        ir_mounts = IR_CONFIGS[self._ir_config]
        ldr_mounts = LDR_MOUNTS

        def ir_val(mount: SensorMount) -> float:
            wx, wy, wa = self._state.sensor_world_pos(mount)
            dist = ray_distance(wx, wy, wa, self._arena, max_range=0.5)
            return ir_reading(dist)

        def ldr_val(mount: SensorMount) -> float:
            wx, wy, _ = self._state.sensor_world_pos(mount)
            illum = light_at(wx, wy, self._arena)
            # ambient floor of ~0.3 when no light source nearby
            illum = max(0.3, illum) if self._arena["light_sources"] else 0.3
            return ldr_reading(illum)

        return SensorReadings(
            RL = ir_val(ir_mounts[0]),
            RR = ir_val(ir_mounts[1]),
            PL = ldr_val(ldr_mounts[0]),
            PR = ldr_val(ldr_mounts[1]),
        )

    # ── Physics tick ───────────────────────────────────────────────────────

    def _tick(self, dt: float):
        sensors = self._read_sensors()
        motors  = self._evaluator.tick(sensors, dt)

        # Save position before move for collision rollback
        old_x, old_y = self._state.x, self._state.y

        self._state.step(motors.left, motors.right, dt)
        self._signals_snap = self._evaluator.signal_snapshot()
        self._signals_snap["_left"]  = motors.left
        self._signals_snap["_right"] = motors.right

        # ── Wall collision ─────────────────────────────────────────────
        # Robot radius approximation: half the body width (~0.047m)
        ROBOT_R = 0.047
        aw = self._arena["width"]  / 2 - ROBOT_R
        ah = self._arena["height"] / 2 - ROBOT_R

        # Collision — stop on contact, no sliding (matches physical robot)
        boundary_hit = (self._state.x < -aw or self._state.x > aw or
                        self._state.y < -ah or self._state.y > ah)
        if boundary_hit:
            self._state.x, self._state.y = old_x, old_y

        # Internal walls — same stop-on-contact behaviour
        for (ax, ay), (bx, by) in self._internal_wall_segments():
            if self._circle_segment_overlap(
                    self._state.x, self._state.y, ROBOT_R,
                    ax, ay, bx, by):
                self._state.x, self._state.y = old_x, old_y
                break

        # Record trace point
        self._trace.append((self._state.x, self._state.y))
        if len(self._trace) > 4000:
            self._trace = self._trace[-4000:]

        # Recorder
        if self._recorder.is_active:
            self._recorder.record(self._state, self._signals_snap, motors)

    def _internal_wall_segments(self) -> list:
        """Return internal wall segments as ((x0,y0),(x1,y1)) pairs."""
        segs = []
        for iw in self._arena.get("internal_walls", []):
            segs.append(((iw["x0"], iw["y0"]), (iw["x1"], iw["y1"])))
        return segs

    @staticmethod
    def _circle_segment_overlap(cx, cy, r, ax, ay, bx, by) -> bool:
        """True if circle (cx,cy,r) overlaps line segment (ax,ay)-(bx,by)."""
        import math
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx*dx + dy*dy
        if seg_len_sq < 1e-12:
            return math.hypot(cx-ax, cy-ay) < r
        t = max(0.0, min(1.0, ((cx-ax)*dx + (cy-ay)*dy) / seg_len_sq))
        nearest_x = ax + t * dx
        nearest_y = ay + t * dy
        return math.hypot(cx - nearest_x, cy - nearest_y) < r

    # ── Main loop ──────────────────────────────────────────────────────────

    def run(self) -> VehicleConfig:
        """Run the simulator. Returns the current VehicleConfig on exit."""
        loop = True
        while loop:
            # Physics
            if self._running:
                now = time.monotonic()
                dt  = min(now - self._last_tick, 0.05)
                self._last_tick   = now
                self._accum      += dt
                self._render_acc += dt
                while self._accum >= PHYS_DT:
                    self._tick(PHYS_DT)
                    self._accum -= PHYS_DT

            # Draw
            self._screen.fill(BG)
            self._btn_rects = {}
            self._draw_canvas()
            self._draw_panel()
            pygame.display.flip()

            # Events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    loop = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        loop = False
                    elif event.key == pygame.K_SPACE:
                        self._toggle_run()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for name, rect in self._btn_rects.items():
                        if rect.collidepoint(event.pos):
                            if not self._handle_btn(name):
                                loop = False
                            break

            self._clock.tick(60)

        pygame.quit()
        return self._config

    def _toggle_run(self):
        if self._running:
            self._stop_sim()
        else:
            self._start_sim()

    def _start_sim(self):
        self._running    = True
        self._last_tick  = time.monotonic()
        self._accum      = 0.0
        os.makedirs(REC_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._recorder.start()
        self._status = "Running  —  Space or ■ Stop to halt"

    def _stop_sim(self):
        self._running = False
        if self._recorder.is_active:
            self._recorder.stop()
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path  = os.path.join(REC_DIR, f"run_{stamp}.vvrec")
            self._recorder.save(path)
            self._status = f"Stopped — saved {os.path.basename(path)}"
        else:
            self._status = "Stopped"

    # ── Button handler ─────────────────────────────────────────────────────

    def _handle_btn(self, name: str) -> bool:
        """Handle button click. Returns False to exit the simulator."""
        if name == "btn_run":
            self._toggle_run()

        elif name == "btn_reset":
            was_running = self._running
            if was_running:
                self._stop_sim()
            self._reset_robot()
            self._status = "Reset — robot at start position"
            if was_running:
                self._start_sim()

        elif name == "btn_wiring":
            self._edit_wiring()

        elif name == "btn_arena":
            self._edit_arena()

        elif name == "btn_quit":
            return False

        return True

    # ── Edit wiring ────────────────────────────────────────────────────────

    def _edit_wiring(self):
        was_running = self._running
        if was_running:
            self._stop_sim()

        # Open the wiring editor in-process.
        # The editor does NOT call pygame.quit() so pygame stays alive.
        # We resize to editor dimensions, editor resizes back on return.
        from valentinos.builder.wiring_editor import WiringEditor
        editor = WiringEditor(initial_config=self._config,
                              title="Edit Vehicle Wiring")
        result = editor.run()

        # Restore simulator window size and caption
        self._screen = pygame.display.set_mode((self._ww, self._wh))
        pygame.display.set_caption("Valentino's Vehicles — Simulator")
        pygame.event.clear()

        if result is not None:
            self._config = result
            self._evaluator = VehicleEvaluator(result)
            self._reset_robot()
            self._status = "Wiring updated — ready to run"
        else:
            self._status = "Wiring edit cancelled"

    # ── Edit arena ─────────────────────────────────────────────────────────

    def _edit_arena(self):
        was_running = self._running
        if was_running:
            self._stop_sim()

        # Save current arena so the builder loads it
        save_arena(self._arena, self._arena_path)

        # Locate arena builder.
        # Priority:
        #   1. ARENA_BUILDER environment variable (explicit override)
        #   2. shared/tools/arena_builder.py  (canonical shared location)
        #   3. robosim sibling layouts         (legacy / dev fallback)
        vv_root      = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(vv_root)

        env_override = os.environ.get("ARENA_BUILDER")
        if env_override and os.path.exists(env_override):
            candidates = [env_override]
        else:
            candidates = [
                # Canonical shared location — preferred
                os.path.join(project_root, "shared",
                             "tools", "arena_builder.py"),
                # Legacy robosim locations — fallback
                os.path.join(project_root, "robosim",
                             "tools", "arena_builder.py"),
                os.path.join(project_root, "robosim_extracted", "robosim",
                             "tools", "arena_builder.py"),
                os.path.join(project_root, "robosim", "robosim",
                             "tools", "arena_builder.py"),
            ]

        builder_path = None
        for c in candidates:
            if os.path.exists(c):
                builder_path = c
                break

        if builder_path:
            # cwd must be the folder containing the robosim package
            # so that `import robosim.theme` resolves
            robosim_root = os.path.dirname(os.path.dirname(builder_path))
            print(f"[valentinos] Launching arena builder: {builder_path}")
            print(f"[valentinos] cwd: {robosim_root}")
            pygame.display.set_mode((1, 1))
            pygame.display.set_caption("")
            result = subprocess.run(
                [sys.executable, builder_path,
                 "--arena", os.path.abspath(self._arena_path)],
                cwd=robosim_root)
            if result.returncode != 0:
                self._status = f"Arena builder exited with code {result.returncode}"
        else:
            msg = (f"Arena builder not found. "
                   f"Searched in {project_root}. "
                   f"Set ARENA_BUILDER env var to override.")
            self._status = msg
            print(f"[valentinos] {msg}")
            print(f"[valentinos] Searched:")
            for c in candidates:
                print(f"  {c}")

        # Restore window — reinit pygame in case subprocess quit it
        pygame.init()
        self._screen = pygame.display.set_mode((self._ww, self._wh))
        pygame.display.set_caption("Valentino's Vehicles — Simulator")
        # Rebuild fonts (invalidated by pygame.quit in subprocess)
        self._font_hd = self._font(19)
        self._font_md = self._font(15)
        self._font_sm = self._font(13)
        pygame.event.clear()

        self._arena = load_arena(self._arena_path)
        self._reset_robot()
        self._status = "Arena updated — ready to run"

    # ── Drawing ────────────────────────────────────────────────────────────

    @property
    def _canvas_rect(self) -> pygame.Rect:
        ww, wh = self._screen.get_size()
        return pygame.Rect(PANEL_W, 0, ww - PANEL_W, wh)

    def _draw_canvas(self):
        traces = {"robot": self._trace} if self._trace else None
        draw_arena(
            self._screen,
            self._canvas_rect,
            self._arena,
            robot_states=[self._state] if True else None,
            traces=traces,
            font_sm=self._font_sm,
        )

    def _draw_panel(self):
        wh = self._screen.get_height()

        # Panel background
        pygame.draw.rect(self._screen, PANEL_COL, (0, 0, PANEL_W, wh))
        pygame.draw.line(self._screen, BORDER,
                         (PANEL_W - 2, 0), (PANEL_W - 2, wh))
        pygame.draw.line(self._screen, WHITE_GREEN,
                         (PANEL_W - 1, 0), (PANEL_W - 1, wh))

        pad = 14
        y   = pad
        w   = PANEL_W - pad * 2

        # Title
        tt = self._font_hd.render("VALENTINO'S", True, WHITE_GREEN)
        self._screen.blit(tt, (pad, y)); y += 22
        tt2 = self._font_hd.render("VEHICLES", True, WHITE_GREEN)
        self._screen.blit(tt2, (pad, y)); y += 28

        self._draw_rule(y); y += 12

        # Run / Stop button
        run_label = "■  Stop" if self._running else "▶  Run"
        run_col   = AMBER if self._running else PHOSPHOR_MID
        self._panel_btn(pad, y, w, 38, run_label, "btn_run",
                        accent=True, color=run_col)
        y += 48

        # Reset
        self._panel_btn(pad, y, w, 32, "↺  Reset", "btn_reset")
        y += 42

        self._draw_rule(y); y += 12

        # Edit buttons
        self._panel_btn(pad, y, w, 32, "Edit Wiring", "btn_wiring")
        y += 42
        self._panel_btn(pad, y, w, 32, "Edit Arena",  "btn_arena")
        y += 42

        self._draw_rule(y); y += 12

        # Meter display — always show all three, unwired stay dim
        if self._signals_snap:
            y = self._draw_meters(pad, y, w, self._signals_snap)

        # Status
        y = wh - 80
        self._draw_rule(y); y += 8
        # Word-wrap status
        words = self._status.split()
        line  = ""
        for word in words:
            test = (line + " " + word).strip()
            if self._font_sm.size(test)[0] <= w:
                line = test
            else:
                self._screen.blit(
                    self._font_sm.render(line, True, TEXT_DIM), (pad, y))
                y += 16
                line = word
        if line:
            self._screen.blit(
                self._font_sm.render(line, True, TEXT_DIM), (pad, y))

        # Quit button at bottom
        self._panel_btn(pad, wh - 34, w, 26, "Exit  [Esc]", "btn_quit")

    def _draw_meters(self, x, y, w, sigs):
        """Vertical 10-segment meter display. M1 left, M2 centre, M3 right.
        Fills bottom-to-top. All three shown; unwired stay dim.
        Returns updated y below the display."""
        from valentinos.engine.signals import WIRE_WEIGHT
        SEGMENTS = 10
        LED_LIT  = {"M1": (220,50,50), "M2": (240,240,240), "M3": (220,50,50)}
        LED_DIM  = {"M1": (60,10,10),  "M2": (60,60,60),    "M3": (60,10,10)}

        lbl = self._font_sm.render("METERS", True, TEXT_DIM)
        self._screen.blit(lbl, (x, y)); y += 14

        gap    = 4
        bar_w  = (w - gap * 2) // 3
        seg_h  = 10
        seg_gap = 2
        bar_h  = SEGMENTS * (seg_h + seg_gap) - seg_gap

        for mi, meter in enumerate(("M1", "M2", "M3")):
            val = 0.0
            for c in self._config.connections:
                if c.dest == meter:
                    val += sigs.get(c.source, 0.0) * WIRE_WEIGHT[c.color]
            val = max(0.0, min(1.0, val))
            lit_segs = int(val * SEGMENTS)
            mx = x + mi * (bar_w + gap)
            for seg in range(SEGMENTS):
                seg_y = y + bar_h - seg * (seg_h + seg_gap) - seg_h
                col   = LED_LIT[meter] if seg < lit_segs else LED_DIM[meter]
                pygame.draw.rect(self._screen, col,
                                 pygame.Rect(mx, seg_y, bar_w, seg_h),
                                 border_radius=2)
            nm = self._font_sm.render(meter, True, TEXT_DIM)
            self._screen.blit(nm, (mx + bar_w//2 - nm.get_width()//2,
                                   y + bar_h + 3))

        return y + bar_h + self._font_sm.get_linesize() + 8

    def _draw_rule(self, y: int):
        pygame.draw.line(self._screen, BORDER, (8, y), (PANEL_W - 8, y))

    def _panel_btn(self, x, y, w, h, label, name,
                   accent=False, disabled=False, color=None):
        rect = pygame.Rect(x, y, w, h)
        self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov  = rect.collidepoint(mx, my) and not disabled
        fill = color if color else (PHOSPHOR_DIM if hov else PANEL_DEEP)
        if disabled:
            fill = (18, 22, 18)
        pygame.draw.rect(self._screen, fill, rect, border_radius=4)
        pygame.draw.rect(self._screen,
                         BORDER if not disabled else (20, 25, 20),
                         rect, 1, border_radius=4)
        tc = TEXT_DIM if disabled else (WHITE_GREEN if accent else TEXT)
        t  = self._font_md.render(label, True, tc)
        self._screen.blit(t, (rect.centerx - t.get_width()  // 2,
                               rect.centery - t.get_height() // 2))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Default: empty vehicle, default arena
    from valentinos.engine.signals import Connection
    config = VehicleConfig(
        connections=[
            Connection("PL", "FL", "blue"),
            Connection("PR", "FR", "blue"),
        ],
        name="Vehicle 2a — Cowardice",
    )
    sim = Simulator(config)
    sim.run()
