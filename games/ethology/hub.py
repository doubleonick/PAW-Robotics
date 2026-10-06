"""
games/ethology/hub.py
----------------------
Robot Ethology game hub.

The hub IS the simulation window. Robots run directly in the hub's
pygame loop — no subprocess spawning. The arena canvas is always
visible; robots appear during observation/experiment runs and
disappear when idle.

States:
  welcome    — instructions on left, empty arena on right
  running    — simulation ticking, timer on left, robots visible
  experiment — experiment controls on left, empty arena on right
"""

import math
import os
import random
import subprocess
import sys
import time
import json

ROOT      = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
GAME_DIR  = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR    = os.path.join(ROOT, "tools")
ARENAS_DIR   = os.path.join(GAME_DIR, "arenas")
_DEFAULT_ARENA = os.path.join(ARENAS_DIR, "arena_default.json")
_SESSION_ARENA = os.path.join(ARENAS_DIR, "session_current.json")


def _clear_session_arena():
    """Remove the per-round working-arena scratch file, if present. Called at
    launch and on Play Again so a player's arena edits never persist across
    sessions or bleed into a new round. The bundle and default arenas (the
    authored content) are never touched."""
    try:
        if os.path.exists(_SESSION_ARENA):
            os.remove(_SESSION_ARENA)
    except OSError:
        pass
sys.path.insert(0, ROOT)
sys.path.insert(0, GAME_DIR)

import pygame
import pybullet as p
import pybullet_data

from engine.config import ArenaConfig, RobotConfig
from engine.layout import Layout
import engine.theme as T
from engine.theme import (
    draw_double_rule, draw_scanlines, draw_led_string,
    draw_panel, draw_btn,
)
from engine.arena.arena_model import ArenaModel
from engine.robot.robot_model import RobotModel
from engine.hal.arduino_hal import ArduinoHAL
from engine.recorder import Recorder
from engine.nav import NavOverlay

def _C():
    """Return current theme colours as a namespace — called each draw."""
    return T

# Colour aliases read dynamically via _C() in draw methods
# T.BG = T.BG  etc — accessed as T.BG directly throughout

# Layout constants — actual values set at runtime from Layout object
# These are used as fallbacks before Hub.__init__ runs
PANEL_W    = 340
MARGIN     = 28
WW         = 1100
WH         = 680
PHYSICS_DT = 1.0 / 120.0
RENDER_DT  = 1.0 / 30.0
OBS_SECS   = 30.0  # DEV


# ── Inline robot runner ───────────────────────────────────────────────────────

class RobotRunner:
    """Manages one robot: model + HAL + recorder."""

    def __init__(self, config, sketch_source, color, label,
                 start_x, start_y, start_heading, physics_client,
                 sketch_is_path: bool = False):
        """
        sketch_source: .ino source code string (default) or file path.
        sketch_is_path: if True, treat sketch_source as a file path
                        (used for player hypothesis sketches).
        """
        self.config  = config
        self.color   = color
        self.label   = label
        self.model   = RobotModel(config, physics_client, color=color)
        self.model.create_body(start_x, start_y, start_heading)
        self.hal     = ArduinoHAL(
            read_callback=self.model.read_pin,
            write_callback=self.model.write_pin,
        )
        if sketch_source:
            if sketch_is_path:
                self.hal.load_sketch(sketch_source)
            else:
                self.hal.load_sketch_from_ino_source(
                    sketch_source, label=f"<{label}>")
            self.hal.call_setup()
            bot = self.hal._namespace.get("bot")
            if bot:
                bot._robot_label = label
                bot._robot_color = color
        self.recorder: Recorder | None = None

    def step(self, arena_body_ids):
        self.hal.call_loop()
        self.model.step(arena_body_ids)

    def check_contacts(self, arena_body_ids, physics_client):
        try:
            bot = self.hal._namespace.get("bot")
            if not (bot and hasattr(bot, "notify_contact")):
                return
            any_contact = False
            for wall_id in arena_body_ids[1:]:
                contacts = p.getContactPoints(
                    bodyA=self.model.body_id,
                    bodyB=wall_id,
                    physicsClientId=physics_client)
                if contacts:
                    any_contact = True
                    break
            if any_contact:
                # Only notify if not in post-escape cooldown
                now = time.monotonic()
                cooldown_until = getattr(bot, "_contact_cooldown_until", 0.0)
                if now >= cooldown_until:
                    bot.notify_contact()
            else:
                if hasattr(bot, "clear_contact"):
                    bot.clear_contact()
        except Exception:
            pass

    def start_recording(self, path):
        self.recorder = Recorder(path)
        self.recorder.start()

    def stop_recording(self):
        if self.recorder and self.recorder.is_active:
            self.recorder.stop()
            self.recorder.save()

    def record_frame(self):
        if self.recorder and self.recorder.is_active:
            self.recorder.record(
                self.model.pos_x, self.model.pos_y, self.model.heading)


# ── Hub ───────────────────────────────────────────────────────────────────────

class Hub:

    def __init__(self, game_state):
        self._gs      = game_state
        self._state   = "welcome"
        self._exit_requested = False
        self._nav = NavOverlay(back_destination="the game menu")
        self._status  = ""
        self._status_col = T.TEXT_DIM
        self._btn_rects  = {}
        self._last_result = ""
        self._show_dlg_in_experiment = False
        # Robot Inspector overlay (read-only specimen view). When set to "A"/"B",
        # the inspector modal is shown for that robot over the experiment screen.
        self._inspect_robot: str | None = None
        self._inspector = None
        self._inspect_close_btn = None
        self._inspect_panel = None

        # Physics
        self._client   = -1
        self._arena_m  = None
        self._runners: list[RobotRunner] = []

        # Run timing
        self._run_start  = 0.0
        self._run_dur    = 0.0   # 0 = unlimited
        self._accumulator = 0.0
        self._render_acc  = 0.0
        self._last_tick   = 0.0
        self._run_mode    = ""   # "observation" | "experiment"
        self._exp_robot   = ""   # "A" or "B" for experiments

        # Recording paths from last observation (keyed by robot label)
        self._obs_recordings: dict[str, str] = {}

        # Physical experiment state
        self._phys_start:     float = 0.0
        self._phys_robot:     str   = ""
        self._phys_hierarchy: list  = []
        self._phys_min_secs:  float = 60.0   # 1 minute minimum

        # BLE physical experiment state
        self._phys_ble:       bool  = False   # True = robot running via BLE
        self._phys_session:   str   = ""      # session token
        self._phys_device:    str   = "RobotA"

        # Playback state
        self._pb_frames:  dict[str, list] = {}   # label → list of Frame
        self._pb_cursor:  float = 0.0            # current time in recording
        self._pb_playing: bool  = False
        self._pb_play_wall: float = 0.0          # wall time when play started
        self._pb_play_rec:  float = 0.0          # recording time when play started
        self._pb_duration:  float = 0.0          # max time across all tracks
        self._pb_labels:    list  = []            # which robots are in playback

        pygame.init()
        # Compute 90% of usable screen
        ww, wh = Layout.compute_window_size(0.90)
        self._layout = Layout(ww, wh)
        # Update module-level globals so helper methods can use them
        global WW, WH, PANEL_W
        WW, WH, PANEL_W = ww, wh, self._layout.panel_w

        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")
        self._clock  = pygame.time.Clock()
        from engine.theme import font_hd, font_md, font_sm, font_lg
        self._font_hd  = font_hd()
        self._font_md  = font_md()
        self._font_sm  = font_sm()
        self._font_lg  = font_lg()

        # Professor Ray
        from engine.professor import DialogueBox
        self._ray_h   = int(self._layout.wh * 0.45)
        self._ray_w   = self._ray_h * 2 // 3
        # Dialogue box: bottom of panel, right of Ray portrait
        from engine.professor import load_script
        self._dlg = DialogueBox(200, 140, T.CURRENT, font_size=16)  # resized at draw time
        self._paw_bot_intro_shown = False

        ETHOLOGY_INTRO = load_script(
            "PAW-BOT", "ethology_intro",
            fallback="PAW-BOT: Welcome to Robot Ethology!")
        self._paw_bot_intro_text = ETHOLOGY_INTRO
        self._last_dlg_time  = 0
        self._dlg.load(ETHOLOGY_INTRO)

        # Clear any leftover working-arena edits from a previous session so they
        # don't bleed into this launch. Edits are per-round scratch, not
        # persistent state.
        _clear_session_arena()
        self._arena_cfg = self._load_arena()
        self._robot_cfg = RobotConfig.from_file(
            os.path.join(GAME_DIR, "robot.json"))

    def _bundle_arena(self):
        """The BUNDLE arena — what the target robots act within. Used by target
        observation, replay, and the reveal, so those are always FAITHFUL to the
        challenge as authored, never affected by the player's own arena edits.
        Precedence: bundle (arena_ref) -> default -> legacy.
        Deliberately ignores session_current.json (the player's working edits).
        """
        candidates = []
        bundle_arena = getattr(self._gs, "arena_ref", None)
        if bundle_arena:
            candidates.append(os.path.join(ARENAS_DIR, bundle_arena))
        candidates += [_DEFAULT_ARENA,
                       os.path.join(GAME_DIR, "ethology_arena.json")]
        for path in candidates:
            if os.path.exists(path):
                return ArenaConfig.from_file(path)
        return ArenaConfig()

    def _working_arena(self):
        """The player's WORKING arena — used when running a HYPOTHESIS and when
        reloading after an edit. If the player has edited/loaded an arena this
        round (session_current.json exists), that takes priority so the
        hypothesis runs in the arena THEY made. Otherwise falls back to the
        bundle arena, then default.
        Precedence: session edit -> bundle (arena_ref) -> default -> legacy.
        """
        candidates = [_SESSION_ARENA]
        bundle_arena = getattr(self._gs, "arena_ref", None)
        if bundle_arena:
            candidates.append(os.path.join(ARENAS_DIR, bundle_arena))
        candidates += [_DEFAULT_ARENA,
                       os.path.join(GAME_DIR, "ethology_arena.json")]
        for path in candidates:
            if os.path.exists(path):
                return ArenaConfig.from_file(path)
        return ArenaConfig()

    # Backwards-compat shim: anything still calling _load_arena gets the
    # bundle arena (the safe default for non-hypothesis contexts).
    def _load_arena(self):
        return self._bundle_arena()

    def _working_arena_path(self) -> str:
        """Filesystem path of the working arena (for passing to subprocesses):
        session edit -> bundle -> default. Mirrors _working_arena()."""
        if os.path.exists(_SESSION_ARENA):
            return _SESSION_ARENA
        bundle = getattr(self._gs, "arena_ref", None)
        bp = os.path.join(ARENAS_DIR, bundle) if bundle else None
        return bp if (bp and os.path.exists(bp)) else _DEFAULT_ARENA


    # ── Physics setup / teardown ──────────────────────────────────────────────

    def _start_physics(self):
        if self._client >= 0:
            self._stop_physics()
        self._client = p.connect(p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath(),
                                   physicsClientId=self._client)
        p.setGravity(0, 0, -9.81, physicsClientId=self._client)
        p.setTimeStep(PHYSICS_DT, physicsClientId=self._client)
        p.setPhysicsEngineParameter(numSolverIterations=50,
                                     physicsClientId=self._client)
        self._arena_m = ArenaModel(self._arena_cfg, self._client)
        self._arena_m.build()

    def _stop_physics(self):
        for r in self._runners:
            r.stop_recording()
        self._runners = []
        if self._client >= 0:
            try:
                p.disconnect(physicsClientId=self._client)
            except Exception:
                pass
            self._client = -1
        self._arena_m = None

    # ── Random start poses ────────────────────────────────────────────────────

    def _random_poses(self, n: int) -> list[tuple]:
        aw = self._arena_cfg.width  / 2 - 0.25
        ah = self._arena_cfg.height / 2 - 0.25
        poses, attempts = [], 0
        while len(poses) < n and attempts < 200:
            x = random.uniform(-aw, aw)
            y = random.uniform(-ah, ah)
            h = random.uniform(0, 2 * math.pi)
            if all(math.hypot(x-px, y-py) > 0.30
                   for px, py, _ in poses):
                poses.append((x, y, h))
            attempts += 1
        while len(poses) < n:
            poses.append((0.0, float(len(poses)) * 0.35, math.pi / 2))
        return poses

    # ── Observation launch ────────────────────────────────────────────────────

    def _start_observation(self):
        self._gs.new_game()
        self._arena_cfg = self._bundle_arena()
        self._start_physics()

        # Prune old observation recordings — keep only last 2 per label
        rec_dir = os.path.join(GAME_DIR, "recordings")
        if os.path.exists(rec_dir):
            import glob as _glob
            for label in ("A", "B"):
                files = sorted(_glob.glob(
                    os.path.join(rec_dir, f"obs_{label}_*.robrec")))
                for old in files[:-2]:   # keep at most 2 most recent
                    try: os.remove(old)
                    except Exception: pass

        # Use arena robot_start as base position if defined;
        # offset the two robots slightly so they don't overlap
        if self._arena_cfg.robot_start_set:
            # Convert builder heading (0=north) to PyBullet Z-rotation (0=east)
            start_h = math.radians(self._arena_cfg.robot_start_deg)
            bx = self._arena_cfg.robot_start_x
            by = self._arena_cfg.robot_start_y
            poses = [
                (round(bx - 0.15, 3), by, start_h),
                (round(bx + 0.15, 3), by, start_h),
            ]
        else:
            poses = self._random_poses(2)
        src_a = self._gs.target_sketch_source("A")
        src_b = self._gs.target_sketch_source("B")

        self._runners = [
            RobotRunner(self._robot_cfg, src_a,
                        T.RED_PH,  "A", *poses[0], self._client),
            RobotRunner(self._robot_cfg, src_b,
                        T.BLUE_PH, "B", *poses[1], self._client),
        ]

        # Start recordings — store paths for later replay
        import datetime
        rec_dir = os.path.join(GAME_DIR, "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rec_a = os.path.join(rec_dir, f"obs_A_{stamp}.robrec")
        rec_b = os.path.join(rec_dir, f"obs_B_{stamp}.robrec")
        self._runners[0].start_recording(rec_a)
        self._runners[1].start_recording(rec_b)
        self._obs_recordings = {"A": rec_a, "B": rec_b}
        # Save arena snapshot alongside recordings for accurate replay
        import json as _json
        _arena_snap = os.path.join(rec_dir, f"obs_arena_{stamp}.json")
        self._obs_arena_snap = _arena_snap
        try:
            with open(_arena_snap, "w", encoding="utf-8") as _f:
                _json.dump({
                    "width":    self._arena_cfg.width,
                    "height":   self._arena_cfg.height,
                    "wall_thickness": self._arena_cfg.wall_thickness,
                    "light_sources": [
                        {"x": ls.x, "y": ls.y, "radius": ls.radius,
                         "intensity": ls.intensity,
                         "color": getattr(ls, "color", "white")}
                        for ls in self._arena_cfg.light_sources],
                    "internal_walls": [
                        {"x0": iw.x0, "y0": iw.y0,
                         "x1": iw.x1, "y1": iw.y1,
                         "thickness": iw.thickness}
                        for iw in self._arena_cfg.internal_walls],
                    "robot_start": {
                        "x": self._arena_cfg.robot_start_x,
                        "y": self._arena_cfg.robot_start_y,
                        "heading_deg": self._arena_cfg.robot_start_deg},
                }, _f, indent=2, ensure_ascii=False)
        except Exception:
            self._obs_arena_snap = None

        self._run_start   = time.monotonic()
        self._run_dur     = OBS_SECS
        self._accumulator = 0.0
        self._render_acc  = 0.0
        self._last_tick   = time.monotonic()
        self._run_mode    = "observation"
        self._state       = "running"

    # ── Experiment launch ─────────────────────────────────────────────────────

    def _start_experiment(self, robot_label: str, sketch_path: str):
        self._arena_cfg = self._working_arena()
        self._start_physics()

        target = self._gs.targets[robot_label]
        # Use arena robot_start if defined, else random
        if self._arena_cfg.robot_start_set:
            # Convert builder heading (0=north) to PyBullet Z-rotation (0=east)
            start_h = math.radians(self._arena_cfg.robot_start_deg)
            poses   = [(self._arena_cfg.robot_start_x,
                        self._arena_cfg.robot_start_y,
                        start_h)]
        else:
            poses = self._random_poses(1)

        self._runners = [
            RobotRunner(self._robot_cfg, sketch_path,
                        target.color, robot_label,
                        *poses[0], self._client,
                        sketch_is_path=True),
        ]

        self._run_start   = time.monotonic()
        self._run_dur     = 0.0   # unlimited — player closes manually
        self._accumulator = 0.0
        self._render_acc  = 0.0
        self._last_tick   = time.monotonic()
        self._run_mode    = "experiment"
        self._exp_robot   = robot_label
        self._state       = "running"

    # ── Playback (recording-based) ────────────────────────────────────────────

    def _start_playback(self, labels: list[str]):
        """Start playback of recorded observation for given robot labels."""
        from engine.recorder import load_recording
        from engine.config import ArenaConfig

        # Restore arena snapshot if available
        snap = getattr(self, "_obs_arena_snap", None)
        if snap and os.path.exists(snap):
            try:
                self._pb_arena_cfg = ArenaConfig.from_file(snap)
            except Exception:
                self._pb_arena_cfg = self._arena_cfg
        else:
            self._pb_arena_cfg = self._arena_cfg

        self._pb_frames  = {}
        self._pb_labels  = []

        COLORS = {"A": T.RED_PH, "B": T.BLUE_PH}

        for label in labels:
            path = self._obs_recordings.get(label, "")
            if path and os.path.exists(path):
                frames = load_recording(path)
                if frames:
                    self._pb_frames[label] = frames
                    self._pb_labels.append(label)

        if not self._pb_labels:
            self._status     = "No recordings available."
            self._status_col = T.AMBER
            return

        self._pb_duration = max(
            self._pb_frames[l][-1].t for l in self._pb_labels)
        self._pb_cursor   = 0.0
        self._pb_playing  = True
        self._pb_play_wall = time.monotonic()
        self._pb_play_rec  = 0.0
        self._state = "playback"

    def _pb_frame_at(self, label: str, t: float):
        """Binary search for frame index at time t."""
        frames = self._pb_frames.get(label, [])
        if not frames:
            return None
        lo, hi = 0, len(frames) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if frames[mid].t < t:
                lo = mid + 1
            else:
                hi = mid
        return frames[lo]

    def _tick_playback(self):
        if not self._pb_playing:
            return
        now     = time.monotonic()
        elapsed = now - self._pb_play_wall
        self._pb_cursor = min(self._pb_play_rec + elapsed, self._pb_duration)
        if self._pb_cursor >= self._pb_duration:
            self._pb_playing = False

    def _pb_seek(self, mouse_x: int):
        """Seek playback to position based on scrubber click."""
        bx = self._layout.arena.left + 10
        bw = self._layout.arena.right - bx - 10
        frac = max(0.0, min(1.0, (mouse_x - bx) / bw))
        self._pb_cursor   = frac * self._pb_duration
        self._pb_play_rec = self._pb_cursor
        self._pb_play_wall = time.monotonic()

    # ── Old sketch-based replay (kept for experiment replay) ──────────────────

    def _start_replay(self, robot_label: str):
        self._arena_cfg = self._bundle_arena()
        self._start_physics()

        target  = self._gs.targets[robot_label]
        src     = self._gs.target_sketch_source(robot_label)
        poses   = self._random_poses(1)

        self._runners = [
            RobotRunner(self._robot_cfg, src,
                        target.color, robot_label,
                        *poses[0], self._client),
        ]

        self._run_start   = time.monotonic()
        self._run_dur     = 0.0
        self._accumulator = 0.0
        self._render_acc  = 0.0
        self._last_tick   = time.monotonic()
        self._run_mode    = "replay"
        self._exp_robot   = robot_label
        self._state       = "running"

    # ── Physics tick (called from main loop when running) ─────────────────────

    def _tick_physics(self):
        now = time.monotonic()
        dt  = min(now - self._last_tick, 0.05)
        self._last_tick   = now
        self._accumulator += dt
        self._render_acc  += dt

        while self._accumulator >= PHYSICS_DT:
            for runner in self._runners:
                runner.step(self._arena_m.body_ids)
            p.stepSimulation(physicsClientId=self._client)
            for runner in self._runners:
                runner.check_contacts(self._arena_m.body_ids, self._client)
            self._accumulator -= PHYSICS_DT

        if self._render_acc >= RENDER_DT:
            for runner in self._runners:
                runner.record_frame()
            self._render_acc -= RENDER_DT

        # Check duration limit
        if self._run_dur > 0:
            if now - self._run_start >= self._run_dur:
                self._finish_run()

    def _finish_run(self):
        for runner in self._runners:
            runner.stop_recording()

        if self._run_mode == "observation":
            self._stop_physics()
            self._state = "experiment"
            self._last_result = ""

        elif self._run_mode == "experiment":
            self._stop_physics()
            # Evaluate hypothesis that was stored when builder was used
            result_path = os.path.join(GAME_DIR, "_hypothesis.json")
            if os.path.exists(result_path):
                with open(result_path) as f:
                    data = json.load(f)
                hypothesis  = data.get("hierarchy", [])
                robot_label = data.get("robot", self._exp_robot)
                os.remove(result_path)
                if hypothesis:
                    try:
                        correct = self._gs.record_experiment(
                            robot_label, hypothesis)
                        self._show_feedback(robot_label, correct)
                    except ValueError as e:
                        self._last_result = str(e)
            self._state = "experiment"

        elif self._run_mode == "replay":
            self._stop_physics()
            self._state = "experiment"

    def _evaluate_experiment(self):
        result_path = os.path.join(GAME_DIR, "_hypothesis.json")
        if not os.path.exists(result_path):
            self._last_result = "No hypothesis on file."
            return
        with open(result_path) as f:
            data = json.load(f)
        hypothesis  = data.get("hierarchy", [])
        robot_label = data.get("robot", self._exp_robot)
        if os.path.exists(result_path):
            os.remove(result_path)
        if not hypothesis:
            return
        try:
            correct = self._gs.record_experiment(robot_label, hypothesis)
            if correct:
                self._last_result = (
                    f"Robot {robot_label}: CORRECT!\n"
                    "That robot is now solved.")
                self._status_col = T.PHOSPHOR
            else:
                rem = self._gs.experiments_remaining
                self._last_result = (
                    f"Robot {robot_label}: not quite.\n"
                    f"{rem} experiments remaining.")
                self._status_col = T.AMBER
        except ValueError as e:
            self._last_result = str(e)
            self._status_col = T.TEXT_DIM

    # ── Canvas drawing ────────────────────────────────────────────────────────

    def _arena_rect(self):
        """Aspect-preserving, inset canvas rect — shared with Field Trip.

        RE previously drew straight into self._layout.arena, so the arena filled
        the window to within MARGIN and the outer walls sat flush against the
        edge (the bottom one reading as clipped). engine.arena.arena_rect adds
        the same 0.92 fit Field Trip always had.
        """
        from engine.arena import arena_rect
        return arena_rect(self._layout.arena,
                          {"width":  self._arena_cfg.width,
                           "height": self._arena_cfg.height})

    def _to_screen(self, wx, wy):
        ar  = self._arena_rect()
        aw  = self._arena_cfg.width
        ah  = self._arena_cfg.height
        scl = min((ar.width  - MARGIN*2) / aw,
                  (ar.height - MARGIN*2) / ah)
        cx  = ar.left + ar.width  // 2
        cy  = ar.top  + ar.height // 2
        return (int(cx + wx * scl), int(cy - wy * scl))

    def _scale(self):
        ar = self._arena_rect()
        return min((ar.width  - MARGIN*2) / self._arena_cfg.width,
                   (ar.height - MARGIN*2) / self._arena_cfg.height)

    def _draw_canvas(self, surf):
        cr = self._layout.arena
        pygame.draw.rect(surf, T.BG, cr)

        # ── Render probe ──────────────────────────────────────────────────────
        # Robot Ethology does NOT draw through engine.arena.draw_arena — it has
        # its own _to_screen/_draw_canvas pair. So the probe in draw_arena can
        # never fire here, which is why an earlier attempt to capture RE's
        # geometry printed nothing at all. Same env var, same output format, so
        # the three games can be compared directly.
        if os.environ.get("PAW_RENDER_PROBE") and not getattr(self, "_probed", False):
            self._probed = True
            _cfg = self._arena_cfg
            _s = self._scale()
            _aw, _ah = _cfg.width * _s, _cfg.height * _s
            _cx = cr.left + cr.width // 2
            _cy = cr.top + cr.height // 2
            from engine.arena import _probe_emit
            _probe_emit(f"[RENDER-PROBE] surf={surf.get_size()} rect={tuple(cr)} "
                  f"arena={_cfg.width}x{_cfg.height} "
                  f"wall_t={_cfg.wall_thickness} "
                  f"scale={_s:.1f}px/m box={_aw:.0f}x{_ah:.0f} "
                  f"top={_cy - _ah/2:.0f} bottom={_cy + _ah/2:.0f} "
                  f"left={_cx - _aw/2:.0f} right={_cx + _aw/2:.0f} "
                  f"[Robot Ethology, own renderer]")

        # During playback, use the arena snapshot from recording time
        cfg = getattr(self, "_pb_arena_cfg", None) \
              if self._state == "playback" else None
        cfg = cfg or self._arena_cfg
        aw, ah = cfg.width, cfg.height
        scl = self._scale()
        t   = cfg.wall_thickness

        # Floor — very dark green
        tl = self._to_screen(-aw/2,  ah/2)
        br = self._to_screen( aw/2, -ah/2)
        floor_rect = pygame.Rect(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1])
        pygame.draw.rect(surf, T.FLOOR, floor_rect)

        # Shadows — cast by internal walls from each light source
        try:
            from engine.render_shadows import draw_shadows
            _arena_dict = {
                "width":  cfg.width, "height": cfg.height,
                "light_sources": [
                    {"x": ls.x, "y": ls.y, "radius": ls.radius,
                     "color": getattr(ls, "color", "white")}
                    for ls in cfg.light_sources],
                "internal_walls": [
                    {"x0": iw.x0, "y0": iw.y0,
                     "x1": iw.x1, "y1": iw.y1}
                    for iw in cfg.internal_walls],
            }
            draw_shadows(surf, _arena_dict, self._to_screen,
                         self._scale(), cr)
        except Exception:
            pass

        # Lights — amber glow pools
        for ls in cfg.light_sources:
            cx, cy = self._to_screen(ls.x, ls.y)
            r_px   = int(ls.radius * scl)
            for ring in range(max(1, r_px), 0, -max(1, r_px//8)):
                alpha = int(60 * (1.0 - ring / r_px))
                s = pygame.Surface((ring*2, ring*2), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 180, 0, alpha), (ring, ring), ring)
                surf.blit(s, (cx - ring, cy - ring))
            pygame.draw.circle(surf, T.LIGHT_COLOR, (cx, cy), max(3, r_px // 6))

        # Internal walls — phosphor green
        for iw in cfg.internal_walls:
            p0 = self._to_screen(iw.x0, iw.y0)
            p1 = self._to_screen(iw.x1, iw.y1)
            wt = max(2, int(iw.thickness * scl))
            # Glow pass — surface is arena-sized, blit at arena left edge
            s  = pygame.Surface((self._layout.arena.width, self._layout.arena.height), pygame.SRCALPHA)
            ax = self._layout.arena.left
            p0g = (p0[0] - ax, p0[1])
            p1g = (p1[0] - ax, p1[1])
            pygame.draw.line(s, (*T.WALL_COLOR, 60), p0g, p1g, wt + 4)
            surf.blit(s, (ax, 0))
            pygame.draw.line(surf, T.WALL_COLOR, p0, p1, wt)

        # Boundary walls — bright phosphor green with glow
        wt = max(3, int(t * scl))
        for p0w, p1w in [
            ((-aw/2-t, ah/2+t), ( aw/2+t,  ah/2+t)),
            ((-aw/2-t,-ah/2-t), ( aw/2+t, -ah/2-t)),
            (( aw/2,  -ah/2),   ( aw/2,    ah/2  )),
            ((-aw/2-t,-ah/2),   (-aw/2-t,  ah/2  )),
        ]:
            p0s = self._to_screen(*p0w)
            p1s = self._to_screen(*p1w)
            # Glow — surface is arena-local, offset screen coords
            ax  = self._layout.arena.left
            gs  = pygame.Surface((self._layout.arena.width, self._layout.arena.height), pygame.SRCALPHA)
            p0g = (p0s[0] - ax, p0s[1])
            p1g = (p1s[0] - ax, p1s[1])
            pygame.draw.line(gs, (*T.PHOSPHOR, 40), p0g, p1g, wt + 6)
            surf.blit(gs, (ax, 0))
            pygame.draw.line(surf, T.WALL_COLOR, p0s, p1s, wt)

        # Robots (only when running)
        if self._state == "running":
            r_px = max(5, int(self._robot_cfg.body_radius * scl))
            for runner in self._runners:
                cx, cy = self._to_screen(runner.model.pos_x,
                                         runner.model.pos_y)
                fill = runner.color
                # Glow ring
                gs = pygame.Surface((self._layout.arena.width, self._layout.arena.height), pygame.SRCALPHA)
                pygame.draw.circle(gs, (*fill, 50), (cx - self._layout.arena.left, cy), r_px + 6)
                surf.blit(gs, (self._layout.arena.left, 0))
                # Body
                edge = tuple(min(255, c + 80) for c in fill)
                pygame.draw.circle(surf, fill, (cx, cy), r_px)
                pygame.draw.circle(surf, edge, (cx, cy), r_px, 2)
                # Heading arrow
                h  = runner.model.heading
                hx = cx + int(math.cos(h) * r_px * 0.85)
                hy = cy - int(math.sin(h) * r_px * 0.85)
                pygame.draw.line(surf, T.WHITE_GREEN, (cx, cy), (hx, hy), 2)
                pygame.draw.circle(surf, T.WHITE_GREEN, (hx, hy), 3)
                # Label
                lt = self._font_sm.render(runner.label, True, (255, 255, 255))
                surf.blit(lt, (cx - lt.get_width()//2,
                               cy - lt.get_height()//2))

        # CRT scanlines over entire canvas
        draw_scanlines(surf, cr, alpha=22)


        # Playback overlay
        if self._state == "playback":
            self._draw_playback_canvas(surf)

        # Physical experiment overlay
        if self._state == "physical":
            self._draw_physical_canvas_overlay(surf)

    def _draw_playback_canvas(self, surf):
        """Draw growing trace + animated robot for playback state."""
        COLORS = {"A": T.RED_PH, "B": T.BLUE_PH}
        r_px   = max(4, int(self._robot_cfg.body_radius * self._scale()))
        t_now  = self._pb_cursor

        for label in self._pb_labels:
            frames = self._pb_frames.get(label, [])
            if not frames:
                continue
            col = COLORS.get(label, (180, 180, 180))

            # Draw trace up to current cursor (growing as it plays)
            prev = None
            cur_frame = None
            for fr in frames:
                if fr.t > t_now:
                    break
                sp = self._to_screen(fr.x, fr.y)
                if prev:
                    pygame.draw.line(surf, col, prev, sp, 2)
                prev = sp
                cur_frame = fr

            # Draw robot at current position
            if cur_frame:
                cx, cy = self._to_screen(cur_frame.x, cur_frame.y)
                edge = tuple(min(255, c + 60) for c in col)
                pygame.draw.circle(surf, col,  (cx, cy), r_px)
                pygame.draw.circle(surf, edge, (cx, cy), r_px, 2)
                h  = math.radians(cur_frame.hdg)
                hx = cx + int(math.cos(h) * r_px * 0.85)
                hy = cy - int(math.sin(h) * r_px * 0.85)
                pygame.draw.line(surf, T.WHITE_GREEN, (cx, cy), (hx, hy), 3)
                lt = self._font_sm.render(label, True, (255, 255, 255))
                surf.blit(lt, (cx - lt.get_width()//2,
                               cy - lt.get_height()//2))

        # Scrubber bar at bottom of canvas
        SCRUB_H = 22
        bx = self._layout.arena.left + 10
        bw = self._layout.arena.right - bx - 10
        by = self._layout.wh - SCRUB_H - 4
        pygame.draw.rect(surf, (28, 34, 50), (bx, by, bw, SCRUB_H),
                         border_radius=4)
        frac = self._pb_cursor / max(0.001, self._pb_duration)
        fw   = max(4, int(bw * frac))
        pygame.draw.rect(surf, T.PHOSPHOR_MID, (bx, by, fw, SCRUB_H),
                         border_radius=4)
        # Cursor handle
        hx2 = bx + int(bw * frac)
        pygame.draw.circle(surf, (255, 255, 255), (hx2, by + SCRUB_H//2), 8)
        self._pb_scrubber = pygame.Rect(bx, by - 4, bw, SCRUB_H + 8)

        # Time label
        mins = int(self._pb_cursor // 60)
        secs = int(self._pb_cursor % 60)
        tl   = self._font_sm.render(
            f"{mins}:{secs:02d} / {int(self._pb_duration//60)}:{int(self._pb_duration%60):02d}",
            True, T.TEXT)
        surf.blit(tl, (bx, by - 18))

        # Play/pause hint
        hint = self._font_sm.render(
            "SPACE = play/pause   click scrubber = seek   Esc = done",
            True, T.TEXT_DIM)
        surf.blit(hint, (self._layout.ww - hint.get_width() - 10, by - 18))

    # ── Panel drawing ─────────────────────────────────────────────────────────

    def _btn(self, surf, rect, label, name,
             accent=False, disabled=False, color=None):
        self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov    = rect.collidepoint(mx, my) and not disabled
        draw_btn(surf, rect, label, self._font_md,
                 active=accent, disabled=disabled,
                 hover=hov, color_override=color)

    def _wrap(self, surf, text, x, y, max_w, col=None):
        col = col or T.TEXT
        fnt = self._font_sm
        for para in text.split("\n\n"):
            words = para.split()
            line  = ""
            for word in words:
                test = (line + " " + word).strip()
                if fnt.size(test)[0] <= max_w:
                    line = test
                else:
                    if line:
                        surf.blit(fnt.render(line, True, col), (x, y))
                        y += fnt.get_linesize() + 1
                    line = word
            if line:
                surf.blit(fnt.render(line, True, col), (x, y))
                y += fnt.get_linesize() + 1
            y += 8
        return y

    def _draw_panel(self, surf):
        lay = self._layout

        # Full panel background
        pygame.draw.rect(surf, T.PANEL, lay.panel)
        # Right-edge fascia
        pygame.draw.line(surf, T.BORDER,
                         (lay.panel.right - 2, 0),
                         (lay.panel.right - 2, self._layout.wh))
        pygame.draw.line(surf, T.WHITE_GREEN,
                         (lay.panel.right - 1, 0),
                         (lay.panel.right - 1, self._layout.wh))

        x = lay.ctrl_inner.x
        w = lay.ctrl_inner.width

        # ── Draw controls region ──────────────────────────────────────────
        if self._state == "welcome":
            self._draw_welcome(surf, x, w)
        elif self._state == "running":
            self._draw_running(surf, x, w)
        elif self._state == "experiment":
            self._draw_experiment(surf, x, w)
        elif self._state == "playback":
            self._draw_playback_panel(surf, x, w)
        elif self._state == "physical":
            self._draw_physical(surf, x, w)

        # ── Divider ───────────────────────────────────────────────────────
        draw_double_rule(surf, 0, lay.narrative.top - 2, self._layout.panel_w)

        # ── Narrative region ──────────────────────────────────────────────
        pygame.draw.rect(surf, T.PANEL_DEEP, lay.narrative)
        self._draw_narrative(surf)

        # ── Back button + confirm overlay ─────────────────────────────────
        self._nav.draw_back_btn(surf, self._layout, self._font_sm, T)
        self._nav.draw_overlay(surf, self._layout.ww, self._layout.wh,
                               self._font_md, self._font_sm, self._btn_rects)

    def _draw_narrative(self, surf):
        """
        Draw the narrative region: dialogue when active, logo when idle.
        This is always below the controls divider line.
        """
        lay  = self._layout
        nr   = lay.narr_inner   # padded narrative rect
        x, y = nr.x, nr.y
        w    = nr.width

        showing_dlg = (
            (self._state == "welcome" and not self._dlg.is_done) or
            (self._state == "experiment" and
             self._show_dlg_in_experiment and not self._dlg.is_done)
        )

        if showing_dlg:
            # Dialogue fills the narrative region
            self._dlg._w = nr.width
            self._dlg._h = nr.height
            self._dlg.draw(surf, nr.x, nr.y)
        else:
            # Narrative region is empty when idle — just the Play Intro button
            # "Play Intro" link bottom-left of narrative
            ir = pygame.Rect(x, nr.bottom - 26, 110, 22)
            self._btn_rects["btn_paw_bot_intro"] = ir
            mx, my = pygame.mouse.get_pos()
            hov = ir.collidepoint(mx, my)
            pygame.draw.rect(surf, T.PANEL_DEEP if not hov else T.PANEL,
                             ir, border_radius=3)
            pygame.draw.rect(surf, T.BORDER, ir, 1, border_radius=3)
            it = self._font_sm.render("Play Intro", True, T.TEXT_DIM)
            surf.blit(it, (ir.centerx - it.get_width()//2,
                           ir.centery - it.get_height()//2))

        # If experiment feedback dialogue done, clear flag
        if self._state == "experiment" and \
                self._show_dlg_in_experiment and self._dlg.is_done:
            self._show_dlg_in_experiment = False

    def _draw_welcome(self, surf, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y

        tt = self._font_hd.render("ROBOT ETHOLOGY", True, T.WHITE_GREEN)
        surf.blit(tt, (x, y)); y += 32
        draw_double_rule(surf, x, y, x+w); y += 14

        # Brief status hint in controls
        hint = self._font_sm.render(
            "Observe A and B  |  20 experiments", True, T.TEXT_DIM)
        surf.blit(hint, (x, y))

        # Continue at bottom of controls region
        btn_h  = 40
        btn_y  = lay.controls.bottom - btn_h - 10
        self._btn(surf, pygame.Rect(x, btn_y, w, btn_h),
                  "CONTINUE  ▶", "btn_continue", accent=True)

    def _draw_running(self, surf, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        mode_label = {
            "observation": "OBSERVATION",
            "experiment":  f"EXPERIMENT \u2014 ROBOT {self._exp_robot}",
            "replay":      f"REPLAY \u2014 ROBOT {self._exp_robot}",
        }.get(self._run_mode, "RUNNING")
        tt = self._font_hd.render(mode_label, True, T.WHITE_GREEN)
        surf.blit(tt, (x, y)); y += 32
        draw_double_rule(surf, x, y, x+w); y += 14

        if self._run_dur > 0:
            elapsed = time.monotonic() - self._run_start
            remain  = max(0.0, self._run_dur - elapsed)
            mins, secs = int(remain // 60), int(remain % 60)
            # LED 7-segment timer
            timer_str = f"{mins:01d}:{secs:02d}"
            led_col   = T.PHOSPHOR if remain > 30 else T.AMBER
            led_x     = x + w//2 - (len(timer_str) * 22) // 2
            draw_led_string(surf, timer_str, led_x, y,
                            char_w=18, char_h=32, color=led_col)
            y += 46
            prog_w = int(w * (1.0 - remain / self._run_dur))
            pygame.draw.rect(surf, (18, 30, 18), (x, y, w, 6))
            if prog_w > 0:
                pygame.draw.rect(surf, led_col, (x, y, prog_w, 6))
            y += 18
        else:
            note = self._font_md.render("ESC OR STOP TO END RUN", True, T.TEXT_DIM)
            surf.blit(note, (x, y)); y += 28

        y += 10
        for runner in self._runners:
            pygame.draw.circle(surf, runner.color, (x+10, y+8), 7)
            pygame.draw.circle(surf, tuple(min(255,c+60) for c in runner.color),
                               (x+10, y+8), 7, 1)
            lt = self._font_md.render(
                f"ROBOT {runner.label}", True, runner.color)
            surf.blit(lt, (x+26, y)); y += 24

        if self._run_mode == "observation":
            y += 8
            note = self._font_sm.render("RECORDING IN PROGRESS", True, T.TEXT_DIM)
            surf.blit(note, (x, y))

        if self._run_mode in ("experiment", "replay"):
            # Anchor STOP below content with a small gap, min 8px from controls bottom
            btn_y = min(y + 12, self._layout.controls.bottom - 50)
            self._btn(surf, pygame.Rect(x, btn_y, w, 40),
                      "STOP RUN", "btn_stop")

    def _draw_experiment(self, surf, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        tt = self._font_hd.render("EXPERIMENTS", True, T.WHITE_GREEN)
        surf.blit(tt, (x, y)); y += 32
        draw_double_rule(surf, x, y, x+w); y += 12

        rem = self._gs.experiments_remaining
        ct  = self._font_md.render(f"Remaining: {rem}", True,
                                    T.PHOSPHOR if rem > 5 else T.AMBER)
        surf.blit(ct, (x, y)); y += 24

        # Solved status
        solved = [l for l, t in self._gs.targets.items() if t.solved]
        if solved:
            st = self._font_sm.render(
                f"Solved: {', '.join(f'Robot {l}' for l in solved)}",
                True, T.PHOSPHOR)
            surf.blit(st, (x, y)); y += 18
        y += 4
        draw_double_rule(surf, x, y, x+w); y += 12

        bh = 40
        for label, name, col, rl in [
            ("Build for A  →", "btn_build_a", T.RED_PH,  "A"),
            ("Build for B  →", "btn_build_b", T.BLUE_PH, "B"),
        ]:
            can = self._gs.can_experiment_on(rl)
            t   = self._gs.targets.get(rl)
            self._btn(surf, pygame.Rect(x, y, w, bh), label, name,
                      color=col if can else None, disabled=not can)
            if t and t.solved:
                tg = self._font_sm.render("✓ solved", True, T.PHOSPHOR)
                surf.blit(tg, (x+6, y+bh+2))
            y += bh + 18
        draw_double_rule(surf, x, y, x+w); y += 12

        # Inspect specimens — opens the read-only Robot Inspector. The
        # ethologist gets a close look at the robots being studied.
        ex_lbl = self._font_sm.render("Inspect specimen:", True, T.TEXT_DIM)
        surf.blit(ex_lbl, (x, y)); y += 18
        hw2 = (w - 4) // 2
        self._btn(surf, pygame.Rect(x, y, hw2, 34),
                  "Robot A", "btn_inspect_a",
                  color=T.RED_PH if self._gs.targets.get("A")
                  and self._gs.targets["A"].morphology else None,
                  disabled=not (self._gs.targets.get("A")
                                and self._gs.targets["A"].morphology))
        self._btn(surf, pygame.Rect(x+hw2+4, y, hw2, 34),
                  "Robot B", "btn_inspect_b",
                  color=T.BLUE_PH if self._gs.targets.get("B")
                  and self._gs.targets["B"].morphology else None,
                  disabled=not (self._gs.targets.get("B")
                                and self._gs.targets["B"].morphology))
        y += 44
        draw_double_rule(surf, x, y, x+w); y += 12

        # Recording replay — only shown while game is still active
        if not self._gs.is_over:
            rl_lbl = self._font_sm.render("Replay observation:", True, T.TEXT_DIM)
            surf.blit(rl_lbl, (x, y)); y += 18
            has_rec = bool(self._obs_recordings)
            hw = (w - 8) // 3 - 2
            self._btn(surf, pygame.Rect(x,          y, hw, 34),
                      "A", "btn_replay_a",
                      color=T.RED_PH  if has_rec else None, disabled=not has_rec)
            self._btn(surf, pygame.Rect(x+hw+4,     y, hw, 34),
                      "B", "btn_replay_b",
                      color=T.BLUE_PH if has_rec else None, disabled=not has_rec)
            self._btn(surf, pygame.Rect(x+(hw+4)*2, y, hw, 34),
                      "Both", "btn_replay_both",
                      color=(100,60,160) if has_rec else None, disabled=not has_rec)
            y += 44
            draw_double_rule(surf, x, y, x+w); y += 12

            # Edit Arena — flows after replay section
            y += 8
            self._btn(surf, pygame.Rect(x, y, w, 36),
                      "\u29c1  Edit Arena", "btn_edit_arena")
            y += 44

        else:
            # Game over — HUD reveal + Play Again fill the controls region
            msg = "Both robots solved!" if all(
                t.solved for t in self._gs.targets.values()) \
                else "No experiments remaining."
            go = self._font_hd.render(msg, True, T.WHITE_GREEN)
            surf.blit(go, (x + w//2 - go.get_width()//2, y)); y += 38

            rev_lbl = self._font_sm.render(
                "Reveal target behavior (with HUD):", True, T.TEXT_DIM)
            surf.blit(rev_lbl, (x, y)); y += 20
            hw2 = (w - 8) // 3 - 2
            self._btn(surf, pygame.Rect(x,           y, hw2, 38),
                      "Robot A", "btn_hud_a",  color=T.RED_PH)
            self._btn(surf, pygame.Rect(x+hw2+4,     y, hw2, 38),
                      "Robot B", "btn_hud_b",  color=T.BLUE_PH)
            self._btn(surf, pygame.Rect(x+(hw2+4)*2, y, hw2, 38),
                      "Both",    "btn_hud_both",
                      color=(160, 80, 200))
            y += 50

            self._btn(surf, pygame.Rect(x, y, w, 40),
                      "Play Again", "btn_new_game", accent=True)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _draw_inspector_overlay(self, surf):
        """Modal overlay hosting the Robot Inspector specimen view."""
        sw, sh = surf.get_size()
        # dim backdrop
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 175))
        surf.blit(dim, (0, 0))
        # centered panel
        pw = min(560, int(sw * 0.6))
        ph = min(620, int(sh * 0.82))
        panel = pygame.Rect((sw - pw) // 2, (sh - ph) // 2, pw, ph)
        self._inspect_panel = panel
        pygame.draw.rect(surf, T.PANEL_DEEP, panel, border_radius=8)
        pygame.draw.rect(surf, T.PHOSPHOR, panel, 2, border_radius=8)
        # close button
        cb = pygame.Rect(panel.right - 40, panel.y + 12, 28, 28)
        if cb.collidepoint(pygame.mouse.get_pos()):
            pygame.draw.rect(surf, T.PANEL, cb, border_radius=4)
        pygame.draw.rect(surf, T.PHOSPHOR, cb, 1, border_radius=4)
        xf = self._font_md.render("\u2715", True, T.PHOSPHOR)
        surf.blit(xf, (cb.centerx - xf.get_width() // 2,
                       cb.centery - xf.get_height() // 2))
        self._inspect_close_btn = cb
        # the specimen view fills the panel interior below the header
        inner = pygame.Rect(panel.x + 12, panel.y + 50,
                            panel.width - 24, panel.height - 64)
        self._inspector.draw(surf, inner)
        hint = self._font_sm.render("Esc or \u2715 to close", True, T.TEXT_DIM)
        surf.blit(hint, (panel.x + 14, panel.bottom - hint.get_height() - 8))

    def _open_inspector(self, robot_label: str):
        """Open the read-only Robot Inspector for robot A or B."""
        t = self._gs.targets.get(robot_label)
        if not t or not t.morphology:
            return
        from engine.ethology.robot_inspector import RobotInspector
        self._inspector = RobotInspector(
            t.morphology, title=f"Robot {robot_label}",
            robot_color=t.color)
        self._inspect_robot = robot_label

    def _close_inspector(self):
        self._inspector = None
        self._inspect_robot = None
        self._inspect_close_btn = None

    def _handle_btn(self, name):

        if name == "btn_continue":
            self._start_observation()

        elif name == "btn_paw_bot_intro":
            self._dlg.load(self._paw_bot_intro_text)
            self._last_dlg_time = int(time.monotonic() * 1000)

        elif name == "btn_stop":
            self._finish_run()

        elif name in ("btn_build_a", "btn_build_b"):
            robot_label = "A" if name == "btn_build_a" else "B"
            self._open_builder(robot_label)

        elif name in ("btn_inspect_a", "btn_inspect_b"):
            self._open_inspector("A" if name == "btn_inspect_a" else "B")

        elif name == "btn_replay_a":
            self._start_playback(["A"])
        elif name == "btn_replay_b":
            self._start_playback(["B"])
        elif name == "btn_replay_both":
            self._start_playback(["A", "B"])

        elif name == "btn_hud_a":
            self._run_hud_reveal(["A"])
        elif name == "btn_hud_b":
            self._run_hud_reveal(["B"])
        elif name == "btn_hud_both":
            self._run_hud_reveal(["A", "B"])

        elif name == "btn_phys_complete":
            self._finish_physical()

        elif name == "btn_edit_arena":
            self._edit_arena()

        elif name == "btn_new_game":
            self._state       = "welcome"
            self._last_result = ""
            self._obs_recordings = {}
            # New round = new bundle arena; discard the previous round's arena
            # edits so they don't carry into the new challenge.
            _clear_session_arena()
            # Reset Ray's intro dialogue for the new game
            self._dlg.load(self._paw_bot_intro_text)
            self._last_dlg_time = int(time.monotonic() * 1000)

    def _draw_physical(self, surf, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        _ble_flag  = getattr(self, "_phys_ble", False)
        mode_tag = "  [BLE]" if _ble_flag else "  [IDE]"
        tt = self._font_hd.render(
            f"PHYSICAL — ROBOT {self._phys_robot}{mode_tag}",
            True, T.WHITE_GREEN)
        surf.blit(tt, (x, y)); y += 32
        draw_double_rule(surf, x, y, x+w); y += 16

        # BLE session indicator
        if getattr(self, "_phys_ble", False) and self._phys_session:
            si = self._font_sm.render(
                f"BLE session: {self._phys_session}", True, T.TEXT_DIM)
            surf.blit(si, (x, y)); y += 18

        # Elapsed clock
        elapsed  = time.monotonic() - self._phys_start
        mins     = int(elapsed // 60)
        secs     = int(elapsed % 60)
        can_done = elapsed >= self._phys_min_secs

        clk_col  = T.PHOSPHOR if can_done else T.TEXT
        clk      = self._font_hd.render(f"{mins:02d}:{secs:02d}", True, clk_col)
        surf.blit(clk, (x + w//2 - clk.get_width()//2, y)); y += 44

        # Minimum time bar
        frac = min(1.0, elapsed / self._phys_min_secs)
        pygame.draw.rect(surf, (28, 34, 50), (x, y, w, 8), border_radius=4)
        if frac > 0:
            pygame.draw.rect(surf, T.PHOSPHOR if can_done else T.PHOSPHOR_MID,
                             (x, y, int(w*frac), 8), border_radius=4)
        y += 18

        if not can_done:
            note = self._font_sm.render(
                f"Minimum {int(self._phys_min_secs)}s not yet elapsed",
                True, T.TEXT_DIM)
            surf.blit(note, (x, y))
        y += 22
        draw_double_rule(surf, x, y, x+w); y += 12

        # Hierarchy reminder
        lbl = self._font_sm.render("Testing hypothesis:", True, T.TEXT_DIM)
        surf.blit(lbl, (x, y)); y += 18
        from games.ethology.codegen import BEHAVIOR_MAP
        for i, key in enumerate(self._phys_hierarchy):
            label = BEHAVIOR_MAP.get(key, (key,))[0]
            col   = T.TEXT if i < len(self._phys_hierarchy)-1 else T.TEXT_DIM
            lt    = self._font_sm.render(f"  {i+1}. {label}", True, col)
            surf.blit(lt, (x, y)); y += 16
        y += 10

        # Complete button
        self._btn(surf,
                  pygame.Rect(x, self._layout.controls.bottom - 50, w, 40),
                  "Experiment Complete", "btn_phys_complete",
                  accent=can_done, disabled=not can_done)

        # Big waiting message on canvas — drawn as overlay
        self._phys_can_done = can_done

    def _draw_physical_canvas_overlay(self, surf):
        """Draw waiting message on arena canvas during physical experiment."""
        if self._state != "physical":
            return
        cx = self._layout.arena.centerx
        cy = self._layout.wh // 2

        # Semi-transparent backing
        aw = self._layout.arena.width
        s  = pygame.Surface((aw - 40, 80), pygame.SRCALPHA)
        s.fill((0, 0, 0, 140))
        surf.blit(s, (self._layout.arena.left + 20, cy - 40))

        msg  = self._font_hd.render(
            "Waiting for physical robot...", True, (255, 215, 70))
        surf.blit(msg, (cx - msg.get_width()//2, cy - msg.get_height()//2))

    def _draw_playback_panel(self, surf, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        lbl = ", ".join(self._pb_labels)
        tt  = self._font_hd.render(f"REPLAY — ROBOT {lbl}", True, T.WHITE_GREEN)
        surf.blit(tt, (x, y)); y += 32
        draw_double_rule(surf, x, y, x+w); y += 16

        # Playback status
        icon = "▶" if self._pb_playing else "⏸"
        st   = self._font_md.render(
            f"{icon}  {int(self._pb_cursor):3d}s / {int(self._pb_duration)}s",
            True, T.TEXT)
        surf.blit(st, (x, y)); y += 28

        # Color legend
        COLORS = {"A": T.RED_PH, "B": T.BLUE_PH}
        for label in self._pb_labels:
            col = COLORS.get(label, T.TEXT)
            pygame.draw.circle(surf, col, (x + 10, y + 8), 8)
            lt = self._font_md.render(f"Robot {label}", True, col)
            surf.blit(lt, (x + 26, y)); y += 26

        y += 12
        note = self._font_sm.render(
            "Scrubber and controls on canvas.", True, T.TEXT_DIM)
        surf.blit(note, (x, y)); y += 20
        note2 = self._font_sm.render(
            "SPACE = play/pause", True, T.TEXT_DIM)
        surf.blit(note2, (x, y)); y += 18
        note3 = self._font_sm.render(
            "Esc = return to experiments", True, T.TEXT_DIM)
        surf.blit(note3, (x, y))

    def _open_builder(self, robot_label: str):
        """Open hierarchy builder as subprocess, then start experiment."""
        result_path = os.path.join(GAME_DIR, "_hypothesis.json")
        if os.path.exists(result_path):
            os.remove(result_path)

        pygame.display.set_mode((1, 1))
        pygame.display.set_caption("")
        builder_script = os.path.join(GAME_DIR, "hierarchy_builder.py")
        subprocess.run(
            [sys.executable,
             builder_script,
             "--robot",  robot_label,
             "--result", result_path,
             "--arena",  self._working_arena_path()],
            cwd=ROOT)
        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")
        pygame.event.clear()

        if not os.path.exists(result_path):
            return

        with open(result_path) as f:
            data = json.load(f)

        if data.get("ble") and not data.get("simulate"):
            # Builder connected via BLE — robot already running
            self._start_physical(robot_label, data)
        elif data.get("simulate"):
            # BLE failed, player chose simulation — run as normal sim
            pass
        elif data.get("physical"):
            # Builder used IDE path — instructor uploads, we wait
            self._start_physical(robot_label, data)
        else:
            sketch_path = data.get("sketch_path", "")
            if sketch_path and os.path.exists(sketch_path):
                self._start_experiment(robot_label, sketch_path)

    def _run_hud_reveal(self, labels: list[str]):
        """
        Run target robot(s) in full simulation window with HUD enabled.
        This is the post-game reveal — sensors and behavior state visible.
        """
        import datetime
        # Reveal shows the TARGET robots, so use the faithful bundle arena
        # (never the player's edits).
        _bundle = getattr(self._gs, "arena_ref", None)
        _bp = os.path.join(ARENAS_DIR, _bundle) if _bundle else None
        arena_cfg_path = _bp if (_bp and os.path.exists(_bp)) else _DEFAULT_ARENA
        robot_cfg_path = os.path.join(GAME_DIR, "robot.json")

        COLORS = {"A": repr(T.RED_PH), "B": repr(T.BLUE_PH)}
        poses  = self._random_poses(len(labels))

        robot_lines = []
        for i, label in enumerate(labels):
            src   = self._gs.target_sketch_source(label)
            # Write to temp file so Simulation.load_sketch can read it
            # (HUD reveal is the ONE place target sketch touches disk
            #  but in a temp location the player won't browse to)
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                suffix=".ino", delete=False,
                prefix=f"hud_reveal_{label}_")
            tmp.write(src.encode())
            tmp.close()
            px, py, ph = poses[i]
            col = T.RED_PH if label == "A" else T.BLUE_PH
            robot_lines.append(
                f"sim.add_robot(robot_cfg, sketch_path={repr(tmp.name)},\n"
                f"    color={repr(col)}, label={repr(label)},\n"
                f"    start_x={px:.4f}, start_y={py:.4f},\n"
                f"    start_heading={ph:.4f})"
            )

        # Primary robot for HUD is the first label
        driver_code = f"""\
import sys, os
sys.path.insert(0, {repr(ROOT)})
import engine.theme as T
T.apply({repr(T.CURRENT)})
from engine.config import ArenaConfig, RobotConfig
from engine.layout import Layout
from engine.simulation import Simulation

arena_cfg = ArenaConfig.from_file({repr(arena_cfg_path)})
robot_cfg  = RobotConfig.from_file({repr(robot_cfg_path)})
sim = Simulation(arena_cfg, show_hud=True,
                 dual_hud={repr(len(labels) > 1)},
                 arena_name="Ethology Arena - Target Behavior",
                 robot_name="Robot {labels[0]}")
{chr(10).join(robot_lines)}
sim.setup()
sim.run()
"""
        driver = os.path.join(GAME_DIR, "_hud_reveal_driver.py")
        with open(driver, "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-\n" + driver_code)

        pygame.display.set_mode((1, 1))
        pygame.display.set_caption("")
        subprocess.run([sys.executable, driver], cwd=ROOT)
        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")
        pygame.event.clear()

    def _show_feedback(self, robot_label: str, correct: bool) -> None:
        """
        Show robot dialogue feedback, then Ray follow-up.
        Loads scripts from scripts/robot_a/ or robot_b/.
        """
        import random
        from engine.professor import load_script
        folder = f"robot_{robot_label.lower()}"

        if correct:
            text = load_script(folder.upper().replace("_", " "),
                               "ethology_correct",
                               fallback=f"ROBOT {robot_label}: Correct!")
        else:
            n    = random.randint(1, 3)
            text = load_script(folder.upper().replace("_", " "),
                               f"ethology_wrong_{n}",
                               fallback=f"ROBOT {robot_label}: Not quite.")

        # Ray follow-up
        targets = self._gs.targets
        solved  = [l for l, t in targets.items() if t.solved]
        if correct:
            if len(solved) == len(targets):
                ray_script = "ethology_both_solved"
            else:
                ray_script = "ethology_one_down"
            paw_bot_text = load_script("PAW-BOT", ray_script, fallback="PAW-BOT: Well done!")
            text = text.strip() + "\n\n" + paw_bot_text.strip()

        # Load into dialogue and make it visible
        self._dlg.load(text)
        self._last_dlg_time = int(time.monotonic() * 1000)
        # Switch to welcome state briefly so dialogue shows, then back
        # Actually — show dialogue in experiment state by updating state
        self._show_dlg_in_experiment = True

    def _start_physical(self, robot_label: str, data: dict):
        """Enter physical experiment state — arena shown, no simulation."""
        self._phys_start     = time.monotonic()
        self._phys_robot     = robot_label
        self._phys_hierarchy = data.get("hierarchy", [])
        self._phys_ble       = bool(data.get("ble",  False))
        self._phys_session   = data.get("session", "")
        self._phys_device    = data.get("device", "RobotA")
        self._state          = "physical"

    def _finish_physical(self):
        """Evaluate physical experiment result — same logic as simulated."""
        # Stop the BLE robot if one is running
        if getattr(self, "_phys_ble", False) and self._phys_session:
            try:
                from engine.bluetooth.robot_bt_client import RobotBLEClient
                client = RobotBLEClient(
                    getattr(self, "_phys_device", "RobotA"))
                result = client.stop(self._phys_session)
                if not result.get("ok"):
                    self._last_result = (
                        f"BLE stop failed: {result.get('error', '?')} "
                        f"— evaluate anyway")
            except Exception as e:
                self._last_result = f"BLE stop error: {e} — evaluate anyway"
            finally:
                self._phys_ble     = False
                self._phys_session = ""

        try:
            correct = self._gs.record_experiment(
                self._phys_robot, self._phys_hierarchy)
            self._show_feedback(self._phys_robot, correct)
        except ValueError as e:
            self._last_result = str(e)
        self._state = "experiment"

    def _edit_arena(self):
        pygame.display.set_mode((1, 1))
        pygame.display.set_caption("")
        # Determine the starting point for the edit: the player's working arena.
        # If they've already edited this round (session file exists) continue
        # from that; otherwise seed from the BUNDLE arena they've been observing
        # (so the first edit restructures the challenge arena).
        if not os.path.exists(_SESSION_ARENA):
            bundle = getattr(self._gs, "arena_ref", None)
            bp = os.path.join(ARENAS_DIR, bundle) if bundle else None
            seed = bp if (bp and os.path.exists(bp)) else _DEFAULT_ARENA
            # Seed the session file from the bundle/default so the editor writes
            # to session_current.json and NEVER overwrites the bundle original
            # (which must stay faithful for replays / Play Again).
            try:
                if os.path.exists(seed):
                    import shutil
                    shutil.copyfile(seed, _SESSION_ARENA)
            except OSError:
                pass
        subprocess.run(
            [sys.executable,
             os.path.join(TOOLS_DIR, "arena_builder.py"),
             "--arena", _SESSION_ARENA],
            cwd=ROOT)
        self._screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption("Robot Ethology")
        # After editing, the working arena reflects the player's edit.
        self._arena_cfg = self._working_arena()
        pygame.event.clear()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            # Physics tick when simulation is running
            if self._state == "running" and self._client >= 0:
                self._tick_physics()

            # Playback tick
            if self._state == "playback":
                self._tick_playback()

            # Dialogue tick (welcome state or experiment feedback)
            now_ms = int(time.monotonic() * 1000)
            if (self._state == "welcome" or
                    (self._state == "experiment" and
                     self._show_dlg_in_experiment)) and \
                    not self._dlg.is_done:
                dt_dlg = (now_ms - self._last_dlg_time) / 1000.0 \
                         if self._last_dlg_time else 0.0
                self._dlg.update(dt_dlg)
            self._last_dlg_time = now_ms

            # Draw
            self._screen.fill(T.BG)
            self._btn_rects = {}
            self._pb_scrubber = pygame.Rect(0, 0, 0, 0)
            self._draw_canvas(self._screen)
            self._draw_panel(self._screen)
            # Robot Inspector overlay — drawn last, on top, when active.
            if self._inspector is not None:
                self._draw_inspector_overlay(self._screen)
            pygame.display.flip()

            if self._exit_requested or self._nav.confirmed:
                running = False

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    # Inspector overlay captures input while open.
                    if self._inspector is not None:
                        if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                            self._close_inspector()
                        continue
                    if self._nav.handle_key(event.key):
                        continue
                    # Dialogue advance in welcome or experiment state
                    if self._state in ("welcome", "experiment") and \
                            not self._dlg.is_done and \
                            (self._state == "welcome" or
                             self._show_dlg_in_experiment):
                        if event.key == pygame.K_SPACE:
                            self._dlg.advance()
                        elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                            self._dlg.skip()
                        if self._state == "welcome":
                            continue
                    elif self._state == "playback":
                        if event.key == pygame.K_ESCAPE:
                            self._state = "experiment"
                        elif event.key == pygame.K_SPACE:
                            if self._pb_playing:
                                self._pb_playing = False
                            else:
                                if self._pb_cursor >= self._pb_duration:
                                    self._pb_cursor = 0.0
                                self._pb_play_wall = time.monotonic()
                                self._pb_play_rec  = self._pb_cursor
                                self._pb_playing   = True
                    elif self._state == "physical":
                        if event.key == pygame.K_ESCAPE:
                            self._state = "experiment"
                    elif event.key == pygame.K_ESCAPE:
                        if self._state == "running":
                            self._finish_run()
                        else:
                            running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    # Inspector overlay captures all clicks while open: the
                    # close button (or a click outside the panel) dismisses it.
                    if self._inspector is not None:
                        if (self._inspect_close_btn and
                                self._inspect_close_btn.collidepoint(event.pos)):
                            self._close_inspector()
                        elif (self._inspect_panel and
                              not self._inspect_panel.collidepoint(event.pos)):
                            self._close_inspector()
                        continue
                    # Nav overlay always gets first priority — never blocked
                    if self._nav.handle_click(event.pos, self._layout,
                                              self._btn_rects):
                        continue
                    # Feedback dialogue advance (experiment state)
                    if self._state == "experiment" and \
                            self._show_dlg_in_experiment and \
                            not self._dlg.is_done:
                        self._dlg.advance()
                        continue
                    # Dialogue advance on click (welcome state)
                    if self._state == "welcome" and not self._dlg.is_done:
                        self._dlg.advance()
                        continue
                    # Replay intro button
                    if "btn_paw_bot_intro" in self._btn_rects and \
                            self._btn_rects["btn_paw_bot_intro"].collidepoint(
                                event.pos):
                        self._dlg.load(self._paw_bot_intro_text)
                        self._last_dlg_time = int(time.monotonic() * 1000)
                        continue
                    if self._state == "playback":
                        if hasattr(self, "_pb_scrubber") and \
                                self._pb_scrubber.collidepoint(event.pos):
                            self._pb_seek(event.pos[0])
                            self._pb_playing = False
                        else:
                            for name, rect in self._btn_rects.items():
                                if rect.collidepoint(event.pos):
                                    self._handle_btn(name)
                                    break
                    else:
                        for name, rect in self._btn_rects.items():
                            if rect.collidepoint(event.pos):
                                self._handle_btn(name)
                                break

                elif event.type == pygame.MOUSEMOTION:
                    if self._state == "playback" and event.buttons[0]:
                        if hasattr(self, '_pb_scrubber') and \
                                self._pb_scrubber.collidepoint(event.pos):
                            self._pb_seek(event.pos[0])

            self._clock.tick(60)

        self._stop_physics()
        pygame.quit()

        self._stop_physics()
        pygame.quit()


if __name__ == "__main__":
    import engine.theme as T
    T.apply(T.load_saved_theme())
    from games.ethology.game import GameState
    gs = GameState()
    Hub(gs).run()
