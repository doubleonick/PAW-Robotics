"""
valentinos/hub.py
------------------
Valentino's Vehicles — main hub.

Launched from the robosim game selector (or directly).
Owns the pygame window, layout, theme, Ray dialogue, and all game states.

States
------
  welcome              Game menu
  vv_intro_offer       PAW-Bot asks "review basics?"
  vv_intro_book        Book recommendation, leads into vehicle demos
  vv_intro_demo_N      Live demo of vehicle N (0-4), manual advance
  vv_intro_wiring      PAW-Bot asks "wiring tutorial?"
  vv_intro_wiring_tut  Wiring tutorial narration
  vv_intro_skip        "Very well!" skip message
  byov_intro           Brief BYOV introduction with PAW-Bot
  byov_build       Wiring editor (full-window, returns here)
  byov_run         Simulation running
  byov_results     Post-run: replay trace, try again, change wiring
  byov_playback    Recording playback (scrubber, HUD)
  ntv_placeholder  Name That Vehicle — coming soon panel
  haf_placeholder  Hunt and Forage — coming soon panel

Layout: left panel (controls/narrative) + right canvas (arena/art)
Theme:  inherits robosim theme selection
"""

from __future__ import annotations
import json
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
def _find_project_root() -> str | None:
    """Walk up from ROOT looking for the project root (contains engine/ package)."""
    p = ROOT
    for _ in range(6):
        if os.path.exists(os.path.join(p, "engine", "theme.py")):
            return p
        p = os.path.dirname(p)
    return None

_PROJECT_ROOT = _find_project_root()
if _PROJECT_ROOT and _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pygame

# ── Theme, Layout, Professor ────────────────────────────────────────────────
import engine.theme as T
from engine.theme import (
    draw_double_rule, draw_scanlines, draw_btn, draw_panel,
    font_hd, font_md, font_sm,
)
from engine.layout import Layout
from engine.nav import NavOverlay
from valentinos.builder.wiring_inspector import WiringInspector
from engine.professor import DialogueBox
import os as _os

def load_script(character: str, script_name: str, fallback: str = "") -> str:
    """
    Load a PAW-Bot script from games/valentinos/scripts/<character>/
    Falls back to engine/professor.load_script (project-level scripts),
    then to the fallback string.
    """
    local_path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "scripts", character.lower(), script_name + ".txt")
    if _os.path.exists(local_path):
        with open(local_path, encoding="utf-8") as f:
            return f.read()
    # Try project-level scripts as fallback
    from engine.professor import load_script as _eng_load
    result = _eng_load(character, script_name, fallback="")
    return result if result else fallback
_HAS_THEME = True
_HAS_PROF  = True
# ── Engine imports ──────────────────────────────────────────────────────────
from valentinos.engine.vehicle  import VehicleConfig, VehicleEvaluator, SensorReadings, Connection
from valentinos.engine.robot_body import (
    RobotState, ir_reading, ldr_reading, IR_CONFIGS, LDR_MOUNTS, SensorMount,
)
from valentinos.engine.recorder import Recorder
from engine.playback import (PlaybackController,
                             PlaybackHUD, RecordingPicker)
from valentinos.engine.signals  import Connection
from valentinos.arena.arena     import (
    load_arena, save_arena, draw_arena, ray_distance, light_at,
)

# ── Constants ───────────────────────────────────────────────────────────────
GAME_DIR   = os.path.join(ROOT, "games", "byov")
ROBOT_JSON  = os.path.join(ROOT, "data", "byov", "robot.json")
WIRING_JSON = os.path.join(ROOT, "data", "byov", "wiring.json")
ARENA_PATH = os.path.join(GAME_DIR, "valentinos_arena.json")
REC_DIR    = os.path.join(GAME_DIR, "recordings")
PHYS_DT    = 1.0 / 120.0
ROBOT_R    = 0.047   # collision radius


# ── Hub ─────────────────────────────────────────────────────────────────────

class Hub:

    def __init__(self, start_state: str = "vv_intro_offer"):
        self._state      = start_state
        self._intro_idx      = 0      # current vehicle demo index (0-4)
        self._inspector      = None   # WiringInspector for current demo
        self._intro_sim  = None   # _NTVSim during vehicle demos
        self._intro_arenas = None # generated once per intro session

        # Vehicle
        # Restore wiring from disk if saved, else use default cowardice wiring
        self._config = self._load_wiring_cfg()
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
        self._recorder        = Recorder()
        self._recording_armed = False   # user toggles before run
        self._pb_ctrl:  PlaybackController | None = None
        self._pb_hud:   PlaybackHUD | None        = None
        self._pb_path:  str | None                = None

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
        self._load_intro_offer()
        self._show_dlg = True

        self._ntv = None   # NTVGame instance when active
        self._exit_requested = False

        # ── Progress / unlock tracking (session-only for dev; TODO: persist) ──
        # Replace with SaveStore.load() / .save() calls when persistence lands.
        self._progress = {
            "intro_done":     False,  # V1-V3b demos completed
            "tutorial_phase": 0,      # 0=not started, 1-8=in progress, 9=done
            "byov_unlocked":  False,  # set True when tutorial_phase==9
            "ntv_unlocked":   False,  # set True when tutorial_phase==9
        }
        # Tutorial working state
        self._tut_phase = 0          # mirrors _progress["tutorial_phase"]
        self._tut_editor_opened = False   # True once wiring editor opened this phase
        # Nav: going Back returns to the game menu
        self._nav_hub   = NavOverlay(back_destination="the game menu")
        # Nav: going Back within a sub-game returns to Valentino's Vehicles
        self._nav_sub   = NavOverlay(back_destination="Valentino's Vehicles")
        self._btn_rects: dict = {}
        self._status = ""

    # ── Intro ──────────────────────────────────────────────────────────────

    def _load_intro(self):
        text = load_script("paw_bot", "vv_intro",
                           fallback="PAW-BOT: Welcome to Valentino's Vehicles!")
        self._dlg.load(text)

    def _load_intro_offer(self):
        text = load_script("paw_bot", "vv_intro_offer",
                           fallback="PAW-BOT: Would you like to review the basics of Vehicles?")
        self._dlg.load(text)
        self._state    = "vv_intro_offer"
        self._show_dlg = True

    def _start_vv_intro_vehicles(self):
        """Begin the V1-V3B vehicle demo sequence."""
        from valentinos.games.ntv.ntv_game import _Sim
        from valentinos.games.ntv.arena_gen import generate_arena
        from valentinos.games.ntv.vehicles import INTRO_ORDER
        import random
        rng = random.Random(42)
        self._intro_arenas = [
            generate_arena(v.motive, rng) for v in INTRO_ORDER
        ]
        self._intro_idx = 0
        # Load book recommendation first
        text = load_script("paw_bot", "vv_intro",
                           fallback="PAW-BOT: Let's explore the vehicles.")
        self._dlg.load(text)
        self._state    = "vv_intro_yes"
        self._show_dlg = True

    def _start_vv_intro_narrate(self, idx: int):
        # Load the vv_intro_narrate_N script.
        # The script has two sections separated by the prediction prompt:
        #   pre-demo pages  — shown before the simulation starts
        #   post-demo pages — shown while the simulation runs
        # The hub starts the simulation when the dialogue advances past
        # the pre-demo section (tracked by _narrate_demo_started).
        script_name = f"vv_intro_narrate_{idx}"
        fallbacks = [
            "PAW-BOT: Vehicle 1 — a single sensor drives speed.",
            "PAW-BOT: Vehicle 2a — ipsilateral, excitatory — the Coward.",
            "PAW-BOT: Vehicle 2b — contralateral, excitatory — the Aggressor.",
            "PAW-BOT: Vehicle 3a — ipsilateral, inhibitory — Love.",
            "PAW-BOT: Vehicle 3b — contralateral, inhibitory — the Explorer.",
        ]
        text = load_script("paw_bot", script_name,
                           fallback=fallbacks[idx])
        self._dlg.load(text)
        self._intro_idx          = idx
        self._state              = f"vv_intro_narrate_{idx}"
        self._show_dlg           = True
        self._intro_sim          = None
        self._narrate_demo_started = False

    def _start_vv_intro_demo(self, idx: int):
        """Start (or restart) the simulation for intro vehicle idx."""
        from valentinos.games.ntv.ntv_game import _Sim
        from valentinos.games.ntv.vehicles import INTRO_ORDER
        vdef  = INTRO_ORDER[idx]
        arena = self._intro_arenas[idx]
        self._intro_sim = _Sim(vdef.config, arena)
        self._inspector = WiringInspector(vdef.config, vdef.full_name)
        self._intro_idx = idx
        self._narrate_demo_started = True

    def _start_vv_intro_demo_standalone(self, idx: int):
        """Start demo and load the old combined script (NTV path, replay)."""
        self._start_vv_intro_demo(idx)
        self._state = f"vv_intro_demo_{idx}"
        _intro_scripts   = ["ntv_intro_v1","ntv_intro_v2a","ntv_intro_v2b",
                            "ntv_intro_v3a","ntv_intro_v3b"]
        _inspect_scripts = ["vv_inspect_v1","vv_inspect_v2a","vv_inspect_v2b",
                            "vv_inspect_v3a","vv_inspect_v3b"]
        intro   = load_script("paw_bot", _intro_scripts[idx],   fallback="")
        inspect = load_script("paw_bot", _inspect_scripts[idx], fallback="")
        sep     = chr(10) + chr(10)
        combined = (intro.strip() + sep + inspect.strip()).strip()
        self._dlg.load(combined)
        self._show_dlg = True

    def _vv_intro_narrate_advance(self):
        """
        Advance the narrate dialogue by one page.
        If the page we are leaving is the prediction prompt, start the
        simulation so it runs while the post-demo commentary plays.
        When all pages are exhausted, move to the next narrate or to
        the wiring offer.
        """
        # Capture the page text BEFORE advancing
        page_leaving = (self._dlg.current_text()
                        if hasattr(self._dlg, "current_text") else "")

        self._dlg.advance()

        # Start sim when player continues past the prediction prompt
        if (not self._narrate_demo_started and
                ("prediction" in page_leaving.lower() or
                 "see if" in page_leaving.lower())):
            self._start_vv_intro_demo(self._intro_idx)

        if self._dlg.is_done:
            from valentinos.games.ntv.vehicles import INTRO_ORDER
            next_idx = self._intro_idx + 1
            if next_idx < len(INTRO_ORDER):
                self._start_vv_intro_narrate(next_idx)
            else:
                self._progress["intro_done"] = True
                text = load_script("paw_bot", "vv_intro_wiring_offer",
                                   fallback="PAW-BOT: Would you like a wiring tutorial?")
                self._dlg.load(text)
                self._state    = "vv_intro_wiring"
                self._show_dlg = True
                self._intro_sim = None

    def _vv_intro_demo_continue(self):
        """Advance from current demo to next demo, or to wiring offer."""
        from valentinos.games.ntv.vehicles import INTRO_ORDER
        next_idx = self._intro_idx + 1
        if next_idx < len(INTRO_ORDER):
            self._start_vv_intro_demo(next_idx)
        else:
            self._progress["intro_done"] = True
            text = load_script("paw_bot", "vv_intro_wiring_offer",
                               fallback="PAW-BOT: Would you like a wiring tutorial?")
            self._dlg.load(text)
            self._state    = "vv_intro_wiring"
            self._show_dlg = True
            self._intro_sim = None

    # ── Wiring Tutorial ──────────────────────────────────────────────────────
    # Phases:
    #  0 = not started
    #  1 = intro + open editor (wire V1: RL→FR, RR→FL blue)
    #  2 = V1 done, run it
    #  3 = edit arena
    #  4 = green wire (RL→FR green, RR→FL blue)
    #  5 = red wires (RL→FR red, RR→FL red)
    #  6 = add meters (RL→M1, RR→M3 added to existing)
    #  7 = rewire as V2a (delete motor wires, add PL→FL, PR→FR)
    #  8 = V2a done, run it — then complete
    #  9 = complete

    def _start_tutorial(self):
        """Enter or resume the wiring tutorial."""
        phase = self._progress["tutorial_phase"]
        if phase == 0:
            phase = 1
            self._progress["tutorial_phase"] = 1
            self._tut_phase = 1
        self._state    = "vv_tut"
        self._tut_editor_opened = False
        self._tut_load_phase(phase)

    def _tut_load_phase(self, phase: int):
        """Load the script and configure controls for the given tutorial phase."""
        self._tut_phase = phase
        self._progress["tutorial_phase"] = phase

        scripts = {
            1: "tut_intro",
            2: "tut_v1_done",
            3: "tut_v1_ran",
            4: "tut_green_wire",
            5: "tut_green_ran",
            6: "tut_red_ran",
            7: "tut_v2a_prompt",
            8: "tut_v2a_done",
        }
        fallbacks = {
            1: "PAW-BOT: Connect RL to FR, then RR to FL. Press Done.",
            2: "PAW-BOT: Well done! Press Run.",
            3: "PAW-BOT: Edit the arena, then run again.",
            4: "PAW-BOT: Change RL to FR to a green wire.",
            5: "PAW-BOT: Change both wires to red.",
            6: "PAW-BOT: Connect RL to M1 and RR to M3.",
            7: "PAW-BOT: Delete motor wires. Connect PL to FL and PR to FR.",
            8: "PAW-BOT: Congratulations! Tutorial complete.",
        }
        if phase in scripts:
            text = load_script("paw_bot", scripts[phase],
                               fallback=fallbacks.get(phase, ""))
            self._dlg.load(text)
            self._show_dlg = True
        self._tut_editor_opened = False
        # Load the correct starting config for this phase
        self._config = self._tut_config_for_phase(phase)
        self._evaluator = VehicleEvaluator(self._config)
        self._reset_robot()
        # Stop any running sim
        self._running = False

    def _tut_config_for_phase(self, phase: int) -> VehicleConfig:
        """Return the expected/starting config for a tutorial phase."""
        if phase <= 1:
            return VehicleConfig()   # empty — player must wire it
        elif phase == 2:
            return VehicleConfig(connections=[
                Connection("RL","FR","blue"), Connection("RR","FL","blue")])
        elif phase == 3:
            return VehicleConfig(connections=[
                Connection("RL","FR","blue"), Connection("RR","FL","blue")])
        elif phase == 4:
            return VehicleConfig(connections=[
                Connection("RL","FR","blue"), Connection("RR","FL","blue")])
        elif phase == 5:
            return VehicleConfig(connections=[
                Connection("RL","FR","green"), Connection("RR","FL","blue")])
        elif phase == 6:
            return VehicleConfig(connections=[
                Connection("RL","FR","red"), Connection("RR","FL","red")])
        elif phase == 7:
            return VehicleConfig(connections=[
                Connection("RL","FR","red"), Connection("RR","FL","red"),
                Connection("RL","M1","blue"), Connection("RR","M3","blue")])
        else:
            return VehicleConfig(connections=[
                Connection("PL","FL","blue"), Connection("PR","FR","blue"),
                Connection("RL","M1","blue"), Connection("RR","M3","blue")])

    def _tut_check_config(self, config: VehicleConfig) -> tuple[bool, str]:
        """
        Check returned config against expected wires for current phase.
        Returns (passed, feedback_script_name).
        """
        conns = {(c.source, c.dest, c.color) for c in config.connections}
        phase = self._tut_phase

        if phase == 1:
            need = {("RL","FR","blue"), ("RR","FL","blue")}
            if need.issubset(conns):
                return True, "tut_v1_done"
            # Diagnose common mistakes
            if ("RL","FL","blue") in conns or ("RR","FR","blue") in conns:
                return False, "tut_v1_wrong"
            return False, "tut_v1_wrong"

        elif phase == 4:
            need = {("RL","FR","green"), ("RR","FL","blue")}
            if need.issubset(conns):
                return True, "tut_green_ran"
            return False, "tut_v1_wrong"   # reuse generic wrong msg

        elif phase == 5:
            need = {("RL","FR","red"), ("RR","FL","red")}
            if need.issubset(conns):
                return True, "tut_red_ran"
            return False, "tut_v1_wrong"

        elif phase == 7:
            # Add meters: RL->M1, RR->M3 (motor wires stay)
            need = {("RL","M1","blue"), ("RR","M3","blue")}
            if need.issubset(conns):
                return True, "tut_meters_done"
            return False, "tut_meters_wrong"

        elif phase == 8:
            # Wire V2a: PL->FL, PR->FR, old motor wires removed
            need   = {("PL","FL","blue"), ("PR","FR","blue")}
            banned = {("RL","FR"), ("RR","FL")}
            motor_gone = not any((s,d) in banned for s,d,_ in conns)
            if need.issubset(conns) and motor_gone:
                return True, "tut_v2a_done"
            return False, "tut_v2a_wrong"

        return True, ""

    def _tut_open_editor(self):
        """Open the wiring editor for the current tutorial phase and check result."""
        from valentinos.builder.wiring_editor import WiringEditor
        title_map = {
            1: "Wire Vehicle 1: RL→FR, RR→FL (blue)",
            4: "Change RL→FR to green",
            5: "Change both wires to red",
            7: "Add meters: RL→M1, RR→M3 (keep motor wires)",
            6: "Add meters: RL→M1, RR→M3",
            7: "Rewire as Vehicle 2a: PL→FL, PR→FR",
        }
        title  = title_map.get(self._tut_phase, "Wiring Editor")
        editor = WiringEditor(initial_config=self._config, title=title)
        result = editor.run()
        # Restore window
        self._screen = pygame.display.set_mode(
            (self._layout.ww, self._layout.wh))
        pygame.display.set_caption("Valentino's Vehicles")
        if _HAS_THEME:
            self._font_hd = font_hd()
            self._font_md = font_md()
            self._font_sm = font_sm()
        pygame.event.clear()
        self._tut_editor_opened = True

        if result is None:
            return   # player cancelled — stay on current phase

        passed, script = self._tut_check_config(result)
        if passed:
            self._config    = result
            self._evaluator = VehicleEvaluator(result)
            self._reset_robot()
            # Advance phase on pass (phase 2,3 advance via Continue not editor)
            next_phase = {1: 2, 4: 5, 5: 6, 7: 8}.get(self._tut_phase)
            if next_phase:
                self._tut_phase = next_phase
                self._progress["tutorial_phase"] = next_phase
            text = load_script("paw_bot", script, fallback="PAW-BOT: Well done!")
            self._dlg.load(text)
            self._show_dlg = True
        else:
            # Wrong wiring — reload with their attempt so they can fix it
            self._config    = result
            self._evaluator = VehicleEvaluator(result)
            text = load_script("paw_bot", script, fallback="PAW-BOT: Try again.")
            self._dlg.load(text)
            self._show_dlg = True

    def _tut_complete(self):
        """Mark the tutorial complete and unlock BYOV + NTV."""
        self._progress["tutorial_phase"] = 9
        self._progress["byov_unlocked"]  = True
        self._progress["ntv_unlocked"]   = True
        self._tut_phase = 9

    def _load_byov_intro(self):
        text = load_script("paw_bot", "byov_intro",
                           fallback="PAW-BOT: Build a vehicle and watch it run.")
        self._dlg.load(text)

    # ── Robot helpers ──────────────────────────────────────────────────────

    def _load_wiring_cfg(self):
        """Load VehicleConfig from wiring.json if it exists, else return default."""
        if os.path.exists(WIRING_JSON):
            try:
                with open(WIRING_JSON) as f:
                    d = json.load(f)
                conns = [
                    Connection(c["source"], c["dest"],
                               c.get("color", "blue"))
                    for c in d.get("connections", [])
                ]
                return VehicleConfig(
                    connections=conns,
                    gain=d.get("gain", 1.0),
                    neuron_biases=d.get("neuron_biases", {}),
                )
            except Exception:
                pass
        # Default: cowardice wiring
        return VehicleConfig(
            connections=[
                Connection("PL", "FL", "blue"),
                Connection("PR", "FR", "blue"),
            ],
            name="Default: Cowardice",
        )

    def _load_robot_cfg(self) -> dict | None:
        """Load custom robot config if saved, else return None (use default)."""
        if os.path.exists(ROBOT_JSON):
            try:
                with open(ROBOT_JSON) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _robot_sensor_names(self) -> list[str]:
        """Return sensor node names for the current robot config."""
        cfg = self._load_robot_cfg()
        if cfg:
            sensors = cfg.get("sensors", {})
            if isinstance(sensors, dict):
                return list(sensors.keys())
            return [s["id"] for s in sensors]
        return ["RL", "RR", "PL", "PR"]

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
        """
        Read sensors using positions from robot.json if available,
        otherwise AnaBBot defaults.  Sensors are keyed by RL/RR/PL/PR.
        """
        cfg = self._load_robot_cfg()
        if cfg and isinstance(cfg.get("sensors"), dict):
            sensors = cfg["sensors"]
            def _mount(key):
                s = sensors.get(key)
                if not s:
                    return None
                return SensorMount(x=s["x_m"], y=s["y_m"],
                                   angle=math.radians(s.get("angle_deg",0)))
            def ir(mount):
                if mount is None: return 0.0
                wx, wy, wa = self._robot.sensor_world_pos(mount)
                return ir_reading(ray_distance(wx, wy, wa, self._arena, 0.5))
            def ldr(mount):
                if mount is None: return 0.0
                wx, wy, _ = self._robot.sensor_world_pos(mount)
                illum = light_at(wx, wy, self._arena)
                illum = max(0.3, illum) if self._arena["light_sources"] else 0.3
                return ldr_reading(illum)
            return SensorReadings(
                RL=ir(_mount("RL")), RR=ir(_mount("RR")),
                PL=ldr(_mount("PL")), PR=ldr(_mount("PR")))

        # AnaBBot defaults
        ir_m = IR_CONFIGS["standard"]
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
        if self._recording_armed:
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
            self._recording_armed = False
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

            # Playback tick
            if self._state == "byov_playback" and self._pb_ctrl:
                self._pb_ctrl.tick()

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

            # VV intro demo tick
            if (self._state.startswith("vv_intro_demo_") or
                    self._state.startswith("vv_intro_narrate_")) and self._intro_sim:
                self._intro_sim.tick(min(dt_wall, 0.05))

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
            # Sub-game Back confirmed → return to welcome state (not full exit)
            if self._nav_sub.confirmed:
                self._nav_sub.reset()
                self._state    = "welcome"
                self._show_dlg = False

            # Hub Back confirmed or explicit exit → full exit
            if self._exit_requested or self._nav_hub.confirmed:
                pygame.quit()
                return

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    if self._nav_hub.handle_key(event.key): pass
                    elif self._nav_sub.handle_key(event.key): pass
                    else: self._on_key(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos
                    _in_sub = self._state not in ("welcome",
                                               "vv_intro_offer",
                                               "vv_intro_skip")
                    _nav    = self._nav_sub if _in_sub else self._nav_hub
                    if not _nav.handle_click(pos, self._layout,
                                             self._btn_rects):
                        self._on_click(pos, 1)

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
        # ── VV intro buttons ────────────────────────────────────────────
        if name == "btn_intro_yes":
            # User wants to review vehicles
            self._start_vv_intro_vehicles()
        elif name == "btn_intro_no":
            # Skip intro — show brief "very well" message then go to welcome
            text = load_script("paw_bot", "vv_intro_skip",
                               fallback="PAW-BOT: Very well! Press Play Intro anytime.")
            self._dlg.load(text)
            self._state    = "vv_intro_skip"
            self._show_dlg = True
        elif name == "btn_intro_skip_continue":
            # Finished skip message — go to game menu
            self._state    = "welcome"
            self._show_dlg = False
        elif name == "btn_vv_intro_yes_continue":
            text = load_script("paw_bot", "vv_intro_book",
                               fallback="PAW-BOT: Here are the five fundamental vehicles.")
            self._dlg.load(text)
            self._show_dlg = True
            self._state    = "vv_intro_book"

        elif name == "btn_vv_book_continue":
            self._start_vv_intro_narrate(0)
        elif name == "btn_intro_replay":
            self._start_vv_intro_demo_standalone(self._intro_idx)
        elif name == "btn_intro_narrate_continue":
            self._vv_intro_narrate_advance()
        elif name == "btn_intro_continue":
            self._vv_intro_demo_continue()
        elif name == "btn_wiring_yes":
            self._start_tutorial()
        elif name == "btn_wiring_no":
            self._state    = "welcome"
            self._show_dlg = False
        elif name == "btn_wiring_tut_done":
            self._state    = "welcome"
            self._show_dlg = False
        elif name == "btn_welcome_tutorial":
            self._start_tutorial()

        # ── Game menu buttons ────────────────────────────────────────────
        elif name == "btn_byov":
            if self._progress["byov_unlocked"]:
                self._state = "byov_intro"
                self._load_byov_intro()
                self._show_dlg = True

        elif name == "btn_ntv":
            if self._progress["ntv_unlocked"]:
                self._launch_ntv()

        elif name == "btn_haf":
            self._state = "haf_placeholder"
            self._show_dlg = False

        elif name == "btn_play_intro":
            self._load_intro_offer()

        # ── BYOV intro ──────────────────────────────────────────────────
        elif name == "btn_build_robot":
            self._open_robot_builder()

        elif name == "btn_byov_continue":
            self._state    = "byov_build"
            self._show_dlg = False
            self._open_wiring_editor()

        # ── BYOV build ──────────────────────────────────────────────────
        elif name == "btn_edit_wiring":
            self._open_wiring_editor()

        elif name == "btn_edit_arena":
            self._open_arena_builder()
            # If in tutorial phase 3, advance after arena edit
            if self._state == "vv_tut" and self._tut_phase == 3:
                text = load_script("paw_bot", "tut_arena_done",
                                   fallback="PAW-BOT: Good. Run again.")
                self._dlg.load(text)
                self._show_dlg = True

        # ── Tutorial buttons ─────────────────────────────────────────────
        elif name == "btn_tut_open_editor":
            self._tut_open_editor()

        elif name == "btn_tut_run":
            self._running   = True
            self._accum     = 0.0
            self._last_tick = time.monotonic()
            self._reset_robot()
            self._state     = "vv_tut"

        elif name == "btn_tut_stop":
            self._running = False
            if self._tut_phase == 2:
                # Ran V1 blue -> show arena edit prompt (phase 3)
                self._tut_phase = 3
                self._progress["tutorial_phase"] = 3
                text = load_script("paw_bot", "tut_v1_ran",
                                   fallback="PAW-BOT: Edit the arena, then run again.")
                self._dlg.load(text); self._show_dlg = True
            elif self._tut_phase in (3, 4):
                # Ran in arena -> upgrade to green wire (phase 4)
                self._tut_phase = 4
                self._progress["tutorial_phase"] = 4
                text = load_script("paw_bot", "tut_green_wire",
                                   fallback="PAW-BOT: Change RL to FR wire to green.")
                self._dlg.load(text); self._show_dlg = True
            elif self._tut_phase == 6:
                # Ran red-wire V1 -> add meters (phase 7)
                self._tut_phase = 7
                self._progress["tutorial_phase"] = 7
                text = load_script("paw_bot", "tut_red_ran",
                                   fallback="PAW-BOT: Now add meters — RL to M1, RR to M3.")
                self._dlg.load(text); self._show_dlg = True
            elif self._tut_phase == 8:
                # Ran V2a -> tutorial complete
                self._tut_complete()
                text = load_script("paw_bot", "tut_v2a_done",
                                   fallback="PAW-BOT: Congratulations!")
                self._dlg.load(text); self._show_dlg = True

        elif name in ("btn_tut_byov", "btn_byov"):
            if self._progress["byov_unlocked"] or self._tut_phase >= 9:
                self._state = "byov_intro"
                self._load_byov_intro()
                self._show_dlg = True

        elif name == "btn_tut_ntv":
            if self._progress["ntv_unlocked"] or self._tut_phase >= 9:
                self._launch_ntv()

        elif name == "btn_run":
            if not self._running:
                self._state = "byov_run"
                self._reset_robot()
                self._start_run()

        # ── BYOV run ────────────────────────────────────────────────────
        elif name == "btn_stop":
            self._stop_run()

        elif name == "btn_arm_rec":
            self._recording_armed = not self._recording_armed
            self._status = ("Recording ARMED — will record next run"
                            if self._recording_armed
                            else "Recording disarmed")

        elif name == "btn_load_rec":
            self._open_recording_picker()

        elif name == "btn_pb_return":
            self._pb_ctrl = None
            self._pb_hud  = None
            self._state   = "byov_results"

        elif name == "btn_pb_replay":
            if self._pb_ctrl:
                self._pb_ctrl.restart()
                self._pb_ctrl.play()

        # ── BYOV results ────────────────────────────────────────────────
        elif name == "btn_run_again":
            self._state = "byov_run"
            self._reset_robot()
            self._start_run()

        elif name == "btn_change_robot":
            self._open_robot_builder()

        elif name == "btn_change_wiring":
            self._state = "byov_build"
            self._open_wiring_editor()

        elif name == "btn_change_arena":
            self._state = "byov_build"
            self._open_arena_builder()

        # ── Placeholders ────────────────────────────────────────────────

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

    def _draw_pb_trace(self, cr: pygame.Rect) -> None:
        """Draw growing past trace + chassis-correct robot for byov_playback."""
        if not self._pb_ctrl:
            return
        from valentinos.arena.arena import world_to_screen, arena_scale
        from valentinos.engine.robot_body import RobotState
        frames = self._pb_ctrl.frames
        cur    = self._pb_ctrl.cursor
        scl    = arena_scale(cr, self._arena)

        C_PAST  = (51, 200, 87)
        C_ROBOT = (51, 255, 87)

        # Growing past trace only — no future trace shown
        prev = None
        for i in range(cur + 1):
            fr = frames[i]
            sp = world_to_screen(fr.x, fr.y, cr, self._arena)
            if prev:
                pygame.draw.line(self._screen, C_PAST, prev, sp, 2)
            prev = sp

        # Robot drawn as chassis polygon (same as live run)
        fr  = frames[cur]
        # Create a temporary RobotState at recorded pose
        rs  = RobotState(x=fr.x, y=fr.y, heading=fr.hdg)
        corners = rs.body_corners()
        screen_corners = [world_to_screen(wx, wy, cr, self._arena)
                          for wx, wy in corners]
        if len(screen_corners) >= 3:
            pygame.draw.polygon(self._screen, (*C_ROBOT, 80),
                                screen_corners)
            pygame.draw.polygon(self._screen, C_ROBOT,
                                screen_corners, 2)
        # Heading arrow
        cx, cy = world_to_screen(fr.x, fr.y, cr, self._arena)
        r_px   = max(5, int(0.047 * scl))
        hx = cx + int(math.cos(fr.hdg) * r_px * 1.6)
        hy = cy - int(math.sin(fr.hdg) * r_px * 1.6)
        pygame.draw.line(self._screen, (220, 255, 220),
                         (cx, cy), (hx, hy), 2)
        pygame.draw.circle(self._screen, (220, 255, 220), (hx, hy), 3)

    def _open_recording_picker(self):
        """Open in-pygame recording browser and start playback."""
        os.makedirs(REC_DIR, exist_ok=True)
        picker = RecordingPicker(title="Select Recording")
        path   = picker.run(REC_DIR, ext=".vvrec",
                            screen=self._screen)
        if not path:
            return
        from valentinos.engine.recorder import load_recording
        frames = load_recording(path)
        if not frames:
            self._status = "Recording is empty"
            return
        self._pb_ctrl = PlaybackController(frames)
        self._pb_hud  = PlaybackHUD(show_hud=True,
                                    accent_color=(51, 200, 87))
        self._pb_path = path
        self._pb_ctrl.play()
        self._state   = "byov_playback"

    def _open_robot_builder(self):
        """Launch the split-screen robot builder."""
        try:
            from valentinos.builder.robot_builder import RobotBuilder
        except ImportError:
            from games.valentinos.builder.robot_builder import RobotBuilder

        robot_cfg, vehicle_cfg = RobotBuilder(
            initial_config=self._config,
            existing_robot=self._load_robot_cfg(),
            window_size=(self._layout.ww, self._layout.wh)).run()

        if robot_cfg is not None:
            # Save physical robot layout to data/byov/robot.json
            os.makedirs(os.path.dirname(ROBOT_JSON), exist_ok=True)
            with open(ROBOT_JSON, "w") as f:
                json.dump(robot_cfg, f, indent=4)
            # Save wiring to wiring.json
            wiring_data = {
                "connections": [
                    {"source": c.source, "dest": c.dest,
                     "color": c.color}
                    for c in vehicle_cfg.connections
                ],
                "gain": vehicle_cfg.gain,
                "neuron_biases": vehicle_cfg.neuron_biases,
            }
            with open(WIRING_JSON, "w") as f:
                json.dump(wiring_data, f, indent=4)
            # Update wiring config and rebuild evaluator
            self._config    = vehicle_cfg
            self._robot_cfg = robot_cfg
            self._evaluator = VehicleEvaluator(vehicle_cfg)
            self._reset_robot()
            self._state  = "byov_build"
            self._status = (f"Robot saved: {robot_cfg['chassis']} chassis, "
                            f"{len(robot_cfg['sensors'])} sensors")

        # Restore display to hub's own layout size
        self._screen = pygame.display.set_mode(
            (self._layout.ww, self._layout.wh))
        pygame.display.set_caption("Valentino's Vehicles")

    def _open_wiring_editor(self):
        from valentinos.builder.wiring_editor import WiringEditor
        # Pass current robot's sensor and motor names so the editor
        # shows the right nodes (custom or AnaBBot default)
        sensor_names = self._robot_sensor_names()
        motor_names  = ["FL", "FR"]   # differential drive always
        editor = WiringEditor(initial_config=self._config,
                              title="Edit Vehicle Wiring",
                              sensor_names=sensor_names,
                              motor_names=motor_names)
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

        # ROOT = games/valentinos/ — go up two levels to reach project root
        project_root = os.path.dirname(os.path.dirname(ROOT))
        candidates   = [
            os.path.join(project_root, "tools", "arena_builder.py"),
        ]
        env = os.environ.get("ARENA_BUILDER")
        if env and os.path.exists(env):
            candidates.insert(0, env)

        builder = next((c for c in candidates if os.path.exists(c)), None)

        if builder:
            engine_root = os.path.dirname(os.path.dirname(builder))
            pygame.display.set_mode((1, 1))
            pygame.display.set_caption("")
            subprocess.run(
                [sys.executable, builder,
                 "--arena", os.path.abspath(ARENA_PATH)],
                cwd=engine_root)
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

        # Return to whichever state called us (tutorial stays in vv_tut,
        # BYOV build panel stays in byov_build, etc.)
        if self._state not in ("vv_tut",):
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

        if state == "byov_playback" and self._pb_ctrl:
            draw_arena(self._screen, cr, self._arena,
                       robot_states=None, traces=None,
                       font_sm=self._font_sm)
            self._draw_pb_trace(cr)
            hud_h = self._pb_hud.panel_height
            hud_r = pygame.Rect(cr.x, cr.bottom - hud_h,
                                cr.width, hud_h)
            self._pb_hud.draw(self._screen, hud_r,
                              self._pb_ctrl,
                              self._font_sm, self._font_md)

        elif state in ("byov_intro", "byov_run", "byov_results", "byov_build"):
            traces = {"robot": self._trace} if self._trace else None
            robots = [self._robot] if state in ("byov_run","byov_results") else None
            draw_arena(self._screen, cr, self._arena,
                       robot_states=robots, traces=traces,
                       font_sm=self._font_sm)
        elif state.startswith("vv_intro_"):
            # Intro states: show live demo if available, else welcome art
            if self._intro_sim and (state.startswith("vv_intro_demo_") or
                                     state.startswith("vv_intro_narrate_")):
                from valentinos.games.ntv.vehicles import INTRO_ORDER
                idx   = self._intro_idx
                arena = self._intro_arenas[idx] if self._intro_arenas else self._arena
                robot_st = [self._intro_sim.robot] if self._intro_sim else None
                draw_arena(self._screen, cr, arena,
                           robot_states=robot_st, font_sm=self._font_sm)
            else:
                self._draw_welcome_art(cr)
        elif state == "vv_tut":
            traces = {"robot": self._trace} if self._trace else None
            robots = [self._robot] if self._running else None
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

        # ── Back button + confirm overlay ──────────────────────────────────
        # Welcome/top-level states go Back to the game menu
        # Sub-game states go Back to Valentino's Vehicles welcome
        _in_subgame = self._state not in ("welcome", "vv_intro_offer",
                                          "vv_intro_skip", "vv_tut")
        _nav = self._nav_sub if _in_subgame else self._nav_hub
        _nav.draw_back_btn(self._screen, self._layout, self._font_sm, T)
        _nav.draw_overlay(self._screen, self._layout.ww, self._layout.wh,
                          self._font_md, self._font_sm, self._btn_rects)

    def _dispatch_controls(self, x, w):
        state = self._state
        if state == "vv_intro_offer":
            self._draw_ctrl_vv_intro_offer(x, w)
        elif state == "vv_intro_yes":
            self._draw_ctrl_vv_intro_yes(x, w)
        elif state == "vv_intro_book":
            self._draw_ctrl_vv_intro_book(x, w)
        elif state.startswith("vv_intro_narrate_"):
            self._draw_ctrl_vv_intro_narrate(x, w)
        elif state.startswith("vv_intro_demo_"):
            self._draw_ctrl_vv_intro_demo(x, w)
        elif state == "vv_intro_wiring":
            self._draw_ctrl_vv_intro_wiring(x, w)
        elif state == "vv_intro_wiring_tut":
            self._draw_ctrl_vv_intro_wiring_tut(x, w)
        elif state == "vv_tut":
            self._draw_ctrl_vv_tut(x, w)
        elif state == "vv_intro_skip":
            self._draw_ctrl_vv_intro_skip(x, w)
        elif state == "welcome":
            self._draw_ctrl_welcome(x, w)
        elif state == "byov_intro":
            self._draw_ctrl_byov_intro(x, w)
        elif state == "byov_build":
            self._draw_ctrl_byov_build(x, w)
        elif state == "byov_run":
            self._draw_ctrl_byov_run(x, w)
        elif state == "byov_results":
            self._draw_ctrl_byov_results(x, w)
        elif state == "byov_playback":
            self._draw_ctrl_byov_playback(x, w)
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

    # ── VV Intro control panels ──────────────────────────────────────────────

    def _draw_ctrl_vv_intro_offer(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        DIM  = T.TEXT_DIM if _HAS_THEME else (70,110,70)
        ACC  = T.PHOSPHOR  if _HAS_THEME else (51,255,87)
        WG   = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        tt = self._font_hd.render("VALENTINO'S", True, WG)
        self._screen.blit(tt, (x, y)); y += 26
        tt2 = self._font_hd.render("VEHICLES", True, WG)
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14
        dlg_ready = (self._dlg is None or self._dlg.is_done or
                     getattr(self._dlg, "is_last_page", False))
        if dlg_ready:
            half = (w - 8) // 2
            self._btn(self._screen, x,        y, half, 38, "Yes", "btn_intro_yes",
                      accent=True,  disabled=False)
            self._btn(self._screen, x+half+8, y, half, 38, "No",  "btn_intro_no",
                      accent=False, disabled=False)

    def _draw_ctrl_vv_intro_yes(self, x, w):
        """Continue panel shown after vv_intro.txt."""
        lay = self._layout
        by  = lay.controls.bottom - 40 - 6
        self._btn(self._screen, x, by, w, 40,
                  "Continue  ▶", "btn_vv_intro_yes_continue", accent=True)

    def _draw_ctrl_vv_intro_book(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        WG  = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        DIM = T.TEXT_DIM    if _HAS_THEME else (70,110,70)
        tt  = self._font_hd.render("VEHICLES", True, WG)
        self._screen.blit(tt, (x, y)); y += 26
        tt2 = self._font_sm.render("by Valentino Braitenberg", True, DIM)
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14
        dlg_done = self._dlg is None or self._dlg.is_done
        self._btn(self._screen, x, lay.controls.bottom - 48, w, 38,
                  "Continue  ▶", "btn_vv_book_continue",
                  accent=dlg_done, disabled=not dlg_done)

    def _draw_ctrl_vv_intro_narrate(self, x, w):
        """Control panel for narrate states — wiring inspector + Continue."""
        from valentinos.games.ntv.vehicles import INTRO_ORDER
        lay  = self._layout
        y    = lay.ctrl_inner.y
        idx  = self._intro_idx
        vdef = INTRO_ORDER[idx]
        AMB  = T.AMBER if _HAS_THEME else (255, 149, 0)

        tt = self._font_md.render(vdef.full_name, True, AMB)
        self._screen.blit(tt, (x, y)); y += 22
        self._rule(self._screen, y); y += 8

        # Show inspector if demo is running in background
        if self._intro_sim:
            btn_h    = 40
            btn_gap  = 6
            insp_bot = lay.controls.bottom - btn_h - btn_gap * 2
            insp_rect = pygame.Rect(x, y, w, max(10, insp_bot - y))
            if self._inspector:
                sigs = self._intro_sim.signal_snapshot()
                self._inspector.draw(
                    self._screen, insp_rect, signals=sigs,
                    font_sm=self._font_sm, font_md=self._font_md)

        # Single Continue button
        btn_h = 40
        btn_gap = 6
        by = lay.controls.bottom - btn_h - btn_gap
        self._btn(self._screen, x, by, w, btn_h,
                  "Continue  ▶", "btn_intro_narrate_continue", accent=True)

    def _draw_ctrl_vv_intro_demo(self, x, w):
        from valentinos.games.ntv.vehicles import INTRO_ORDER
        lay  = self._layout
        y    = lay.ctrl_inner.y
        idx  = self._intro_idx
        vdef = INTRO_ORDER[idx]
        AMB  = T.AMBER if _HAS_THEME else (255,149,0)

        # Header
        tt = self._font_md.render(vdef.full_name, True, AMB)
        self._screen.blit(tt, (x, y)); y += 22
        self._rule(self._screen, y); y += 8

        # Wiring inspector fills the controls region above the buttons
        btn_h    = 40
        btn_gap  = 6
        insp_bot = lay.controls.bottom - btn_h - btn_gap * 2
        insp_rect = pygame.Rect(x, y, w, max(10, insp_bot - y))
        if self._inspector:
            sigs = self._intro_sim.signal_snapshot()                    if self._intro_sim else {}
            self._inspector.draw(
                self._screen, insp_rect, signals=sigs,
                font_sm=self._font_sm, font_md=self._font_md)

        # Replay / Continue
        half = (w - btn_gap) // 2
        by   = lay.controls.bottom - btn_h - btn_gap
        self._btn(self._screen, x,              by, half, btn_h,
                  "↺  Replay",   "btn_intro_replay",   accent=False)
        self._btn(self._screen, x+half+btn_gap, by, half, btn_h,
                  "Continue  ▶", "btn_intro_continue", accent=True)

    def _draw_ctrl_vv_intro_wiring(self, x, w):
        lay  = self._layout
        y    = lay.ctrl_inner.y
        WG   = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        tt   = self._font_hd.render("WIRING", True, WG)
        self._screen.blit(tt, (x, y)); y += 26
        tt2  = self._font_hd.render("TUTORIAL", True, WG)
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14
        dlg_done = self._dlg is None or self._dlg.is_done
        half = (w - 8) // 2
        self._btn(self._screen, x,        lay.controls.bottom - 48, half, 38,
                  "Yes", "btn_wiring_yes",
                  accent=dlg_done, disabled=not dlg_done)
        self._btn(self._screen, x+half+8, lay.controls.bottom - 48, half, 38,
                  "No",  "btn_wiring_no",
                  accent=False, disabled=not dlg_done)

    def _draw_ctrl_vv_intro_wiring_tut(self, x, w):
        lay  = self._layout
        y    = lay.ctrl_inner.y
        WG   = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        tt   = self._font_hd.render("WIRING", True, WG)
        self._screen.blit(tt, (x, y)); y += 26
        tt2  = self._font_hd.render("TUTORIAL", True, WG)
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14
        dlg_done = self._dlg is None or self._dlg.is_done
        self._btn(self._screen, x, lay.controls.bottom - 48, w, 38,
                  "Done  ▶", "btn_wiring_tut_done",
                  accent=dlg_done, disabled=not dlg_done)

    def _draw_ctrl_vv_intro_skip(self, x, w):
        lay  = self._layout
        y    = lay.ctrl_inner.y
        WG   = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        tt   = self._font_hd.render("VALENTINO'S", True, WG)
        self._screen.blit(tt, (x, y)); y += 26
        tt2  = self._font_hd.render("VEHICLES", True, WG)
        self._screen.blit(tt2, (x, y)); y += 30
        self._rule(self._screen, y); y += 14
        dlg_done = self._dlg is None or self._dlg.is_done
        self._btn(self._screen, x, lay.controls.bottom - 48, w, 38,
                  "Let's Go  ▶", "btn_intro_skip_continue",
                  accent=dlg_done, disabled=not dlg_done)

    # ── Welcome ───────────────────────────────────────────────────────────────

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

        byov_on  = self._progress["byov_unlocked"]
        ntv_on   = self._progress["ntv_unlocked"]
        tut_on   = self._progress["intro_done"]
        DIM      = T.TEXT_DIM    if _HAS_THEME else (70,110,70)
        ACC      = T.PHOSPHOR    if _HAS_THEME else (51,255,87)
        AMB      = T.AMBER       if _HAS_THEME else (255,149,0)
        BTN_H    = 34   # button height
        SUB_H    = 16   # sub-label height below button
        ROW_H    = BTN_H + SUB_H + 6   # total row height

        # ── Wiring Tutorial ───────────────────────────────────────────────
        self._btn(self._screen, x, y, w, BTN_H, "Wiring Tutorial",
                  "btn_welcome_tutorial",
                  accent=tut_on, disabled=not tut_on)
        if not tut_on:
            lk = self._font_sm.render("complete the intro first", True, DIM)
            self._screen.blit(lk, (x, y + BTN_H + 2))
        elif self._progress["tutorial_phase"] == 9:
            lk = self._font_sm.render("✓ complete", True, ACC)
            self._screen.blit(lk, (x, y + BTN_H + 2))
        elif self._progress["tutorial_phase"] > 0:
            lk = self._font_sm.render("in progress — tap to resume", True, AMB)
            self._screen.blit(lk, (x, y + BTN_H + 2))
        y += ROW_H

        self._rule(self._screen, y); y += 8

        # ── Games ─────────────────────────────────────────────────────────
        games = [
            ("Build Your Own Vehicle", "btn_byov", byov_on,
             "complete the tutorial to unlock"),
            ("Name That Vehicle",      "btn_ntv",  ntv_on,
             "complete the tutorial to unlock"),
            ("Hunt and Forage",        "btn_haf",  False,
             "coming soon"),
        ]
        for label, name, avail, locked_msg in games:
            col = (T.PHOSPHOR_MID if _HAS_THEME else (30,160,50)) if avail else None
            self._btn(self._screen, x, y, w, BTN_H, label, name,
                      accent=avail, disabled=not avail, color=col)
            if not avail:
                lk = self._font_sm.render(locked_msg, True, DIM)
                self._screen.blit(lk, (x, y + BTN_H + 2))
            y += ROW_H



    def _draw_ctrl_vv_tut(self, x, w):
        """
        Tutorial control panel. Content adapts to current phase.
        Phases that need the editor show an "Open Wiring Editor" button.
        Phases that need running show Run/Stop.
        Phases 8/9 show navigation to BYOV and NTV.
        """
        lay   = self._layout
        y     = lay.ctrl_inner.y
        phase = self._tut_phase
        WG    = T.WHITE_GREEN if _HAS_THEME else (220,255,220)
        DIM   = T.TEXT_DIM    if _HAS_THEME else (70,110,70)
        AMB   = T.AMBER       if _HAS_THEME else (255,149,0)
        ACC   = T.PHOSPHOR    if _HAS_THEME else (51,255,87)

        # Title
        tt = self._font_md.render("WIRING TUTORIAL", True, WG)
        self._screen.blit(tt, (x, y)); y += 22
        phase_labels = {
            1: "Step 1: Wire Vehicle 1",
            2: "Step 2: Run Vehicle 1",
            3: "Step 3: Edit the Arena",
            4: "Step 4: Upgrade a Wire",
            5: "Step 5: Red Wires",
            6: "Step 6: Run — observe red wires",
            7: "Step 7: Add Meters",
            8: "Step 8: Run Vehicle 2a",
            9: "Tutorial Complete  ✓",
        }
        sub = self._font_sm.render(phase_labels.get(phase, ""), True, AMB)
        self._screen.blit(sub, (x, y)); y += 18
        self._rule(self._screen, y); y += 10

        dlg_done = self._dlg is None or self._dlg.is_done
        btn_y    = lay.controls.bottom - 48
        half     = (w - 6) // 2

        # Show WiringInspector for relevant phases
        if phase in (2, 3, 4, 5, 6, 7, 8, 9):
            insp_bot  = btn_y - 6
            insp_rect = pygame.Rect(x, y, w, max(10, insp_bot - y))
            if self._inspector is None or self._tut_editor_opened:
                from valentinos.builder.wiring_inspector import WiringInspector
                self._inspector = WiringInspector(self._config, "Current Wiring")
            sigs = self._signals_snap if self._running else {}
            self._inspector.draw(self._screen, insp_rect,
                                 signals=sigs,
                                 font_sm=self._font_sm,
                                 font_md=self._font_md)

        # Bottom buttons vary by phase
        if phase == 9:
            # Complete — show BYOV and NTV
            self._btn(self._screen, x,        btn_y, half, 38,
                      "Build Your Own Vehicle", "btn_tut_byov", accent=True)
            self._btn(self._screen, x+half+6, btn_y, half, 38,
                      "Name That Vehicle",      "btn_tut_ntv",  accent=True)

        elif phase in (1, 4, 5, 7):
            # Open editor: P1=wire V1, P4=green, P5=red wires, P7=meters
            self._btn(self._screen, x, btn_y, w, 38,
                      "Open Wiring Editor  →", "btn_tut_open_editor",
                      accent=dlg_done, disabled=not dlg_done)

        elif phase in (2, 6, 8):
            # Run: P2=V1 blue, P6=V1 red, P8=V2a
            if self._running:
                self._btn(self._screen, x, btn_y, w, 38,
                          "■  Stop", "btn_tut_stop", accent=False)
            else:
                self._btn(self._screen, x, btn_y, w, 38,
                          "▶  Run", "btn_tut_run",
                          accent=dlg_done, disabled=not dlg_done)

        elif phase == 3:
            # Edit arena, then run
            if self._running:
                self._btn(self._screen, x, btn_y, w, 38,
                          "■  Stop", "btn_tut_stop", accent=False)
            else:
                self._btn(self._screen, x,        btn_y, half, 38,
                          "Edit Arena", "btn_edit_arena", accent=False)
                self._btn(self._screen, x+half+6, btn_y, half, 38,
                          "▶  Run", "btn_tut_run",
                          accent=dlg_done, disabled=not dlg_done)

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

        # Continue and Build Robot anchored to bottom of controls
        btn_y = lay.controls.bottom - 48
        self._btn(self._screen, x, btn_y, w, 38,
                  "Build Robot  →", "btn_build_robot", accent=True)

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
                  "Edit Robot",  "btn_build_robot")
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "Edit Arena",  "btn_edit_arena")
        y += 44

        # Live sensor preview (one tick, no state change)
        try:
            s = self._read_sensors()
            sn = self._evaluator.signal_snapshot()
            DIM  = T.TEXT_DIM  if _HAS_THEME else (70,110,70)
            ACC  = T.PHOSPHOR  if _HAS_THEME else (51,255,87)
            col  = T.TEXT      if _HAS_THEME else (160,220,160)
            sv = self._font_sm.render("Sensors:", True, DIM)
            self._screen.blit(sv, (x, y)); y += 16
            for name, val in [("RL", s.RL), ("RR", s.RR),
                               ("PL", s.PL), ("PR", s.PR)]:
                bar_w = int(val * (w - 38))
                pygame.draw.rect(self._screen, DIM,
                                 pygame.Rect(x+30, y+2, w-38, 9),
                                 border_radius=2)
                if bar_w > 0:
                    pygame.draw.rect(self._screen, ACC,
                                     pygame.Rect(x+30, y+2, bar_w, 9),
                                     border_radius=2)
                lv = self._font_sm.render(f"{name}", True, col)
                self._screen.blit(lv, (x, y)); y += 13
            y += 4
        except Exception:
            pass

        # Rec toggle + Run at bottom of byov_build
        btn_y = lay.controls.bottom - 96
        rec_lbl = ("⏺  Rec ARMED" if self._recording_armed
                   else "○  Arm Rec")
        self._btn(self._screen, x, btn_y, w, 34,
                  rec_lbl, "btn_arm_rec", accent=self._recording_armed)
        btn_y += 44
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

    def _draw_ctrl_byov_playback(self, x, w):
        lay = self._layout
        y   = lay.ctrl_inner.y
        tt  = self._font_hd.render("PLAYBACK", True, (51, 200, 87))
        self._screen.blit(tt, (x, y)); y += 30
        if self._pb_path:
            import os as _os3
            nm = _os3.path.basename(self._pb_path)
            nl = self._font_sm.render(nm[:28], True, (60, 120, 60))
            self._screen.blit(nl, (x, y)); y += 20
        self._rule(self._screen, y); y += 14
        if self._pb_ctrl and self._pb_ctrl.is_done:
            self._btn(self._screen, x, y, w, 34,
                      "↺  Replay Again", "btn_pb_replay", accent=True)
            y += 44
        self._btn(self._screen, x, y, w, 34,
                  "⬅  Return to Workspace", "btn_pb_return")

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
                  "Edit Robot",      "btn_change_robot")
        y += 44
        self._btn(self._screen, x, y, w, 34,
                  "Edit Arena",      "btn_change_arena")
        y += 44
        import os as _os2
        has_recs = (_os2.path.isdir(REC_DIR) and
                    any(f.endswith(".vvrec")
                        for f in _os2.listdir(REC_DIR)))
        if has_recs:
            self._btn(self._screen, x, y, w, 34,
                      "⏵  Load Recording", "btn_load_rec")
            y += 44


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



    # ── Narrative ──────────────────────────────────────────────────────────

    def _draw_narrative(self):
        lay  = self._layout
        nr   = lay.narr_inner

        if self._show_dlg and not self._dlg.is_done:
            self._dlg._w = nr.width
            self._dlg._h = nr.height - 20   # leave room for hint
            self._dlg.draw(self._screen, nr.x, nr.y)
            # "Press Space to advance" hint at bottom of narration panel
            DIM  = T.TEXT_DIM if _HAS_THEME else (70, 110, 70)
            hint = self._font_sm.render("Press  Space  to advance...", True, DIM)
            self._screen.blit(hint,
                              (nr.x + nr.width  // 2 - hint.get_width()  // 2,
                               nr.bottom - hint.get_height() - 2))
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
    import argparse
    ap = argparse.ArgumentParser(
        description="Valentino's Vehicles")
    ap.add_argument(
        "--state", default=None,
        help=(
            "Dev: jump directly to a game state, bypassing all unlock "
            "checks.  Valid states: "
            "vv_intro_offer, vv_intro_book, vv_intro_narrate_N (0-4), "
            "vv_intro_wiring, welcome, vv_tut, "
            "byov_intro, byov_build, byov_run, ntv.  "
            "Example:  python hub.py --state byov_intro"
        ))
    ap.add_argument(
        "--phase", type=int, default=None,
        help="Dev: start wiring tutorial at a specific phase (1-8). "
             "Only used when --state vv_tut is set.")
    args = ap.parse_args()

    if _HAS_THEME:
        T.apply(T.load_saved_theme())

    if args.state:
        # Dev mode — force state and unlock everything
        hub = Hub(start_state=args.state)
        # Unlock all sub-games unconditionally
        hub._progress["byov_unlocked"] = True
        hub._progress["ntv_unlocked"]  = True
        hub._progress["intro_done"]    = True
        hub._progress["tutorial_phase"] = 9
        hub._tut_phase = 9
        # If jumping into tutorial at a specific phase
        if args.state == "vv_tut" and args.phase is not None:
            phase = max(1, min(8, args.phase))
            hub._progress["tutorial_phase"] = phase
            hub._tut_phase = phase
            hub._tut_load_phase(phase)
        # If jumping into NTV launch it directly
        if args.state == "ntv":
            hub._launch_ntv()
        hub.run()
    else:
        Hub().run()


if __name__ == "__main__":
    main()
