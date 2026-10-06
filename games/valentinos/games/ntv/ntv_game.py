"""
valentinos/games/ntv/ntv_game.py
---------------------------------
Name That Vehicle — complete game state machine.

Called from hub.py when the player selects "Name That Vehicle".
The hub passes its screen, layout, fonts, and clock each frame.
NTVGame owns all NTV state; the hub just forwards events and draw calls.

States
------
  intro_narrate_N   Ray narrates vehicle N (0-4), View Demo button appears
  intro_demo_N      5-second live demo of vehicle N
  intro_task        Ray explains the game task
  round_run         5-second live run of mystery vehicle
  round_guess       Player selects from choice list, presses Verify
  round_result      Feedback shown; View Wiring / Next buttons
  done              Session ended (player pressed Back to Menu)
"""

from __future__ import annotations
import math
import os
import random
import time

import pygame
from engine.nav import NavOverlay

from engine.vehicle import VehicleEvaluator
from engine.robot_body import (
    RobotState, ir_reading, ldr_reading,
    IR_CONFIGS, LDR_MOUNTS,
)
from engine.arena                  import draw_arena, ray_distance, light_at
from valentinos.games.ntv.vehicles import (
    INTRO_ORDER, BEHAVIOR_NAMES,
    make_compound, VehicleDef,
)
from valentinos.games.ntv.rounds import (
    Round, RoundSequence, NTVAnswer, COLUMN_CHOICES, NA, SessionScore,
)
from valentinos.games.ntv.arena_gen import generate_arena
from valentinos.games.ntv.progress  import (
    load as load_progress, save as save_progress,
    mark_intro_seen, record_session,
)

# ── Colour constants (theme-independent) ──────────────────────────────────────
_BG          = (10,  12,  10)
_PANEL       = (13,  15,  13)
_PANEL_DEEP  = ( 8,  10,   8)
_BORDER      = (30,  58,  30)
_TEXT        = (160, 220, 160)
_TEXT_DIM    = ( 70, 110,  70)
_TEXT_BRIGHT = (220, 255, 220)
_PHOSPHOR    = ( 51, 255,  87)
_PHOSPHOR_MID= ( 30, 160,  50)
_AMBER       = (255, 149,   0)
_WHITE_GREEN = (220, 255, 220)
_RED         = (220,  60,  60)
_CYAN        = ( 60, 230, 230)

def _get_T():
    """Return current engine.theme module, or None if unavailable."""
    try:
        import engine.theme as _t
        return _t
    except Exception:
        return None

DEMO_SECS   = 12.0
ROUND_SECS  = 12.0
PHYS_DT     = 1.0 / 120.0
ROBOT_R     = 0.047

# Question variants shown at random
QUESTION_VARIANTS = [
    "What would you call this one?",
    "Name that vehicle:",
    "Can you guess which vehicle that was?",
    "What did that one look like to you?",
]

# Scripts path
_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))),
    "scripts", "paw_bot")


def _load_script(name: str) -> str:
    path = os.path.join(_SCRIPTS, f"{name}.txt")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return f"PAW-BOT: {name}"


# ── Simulation helper ─────────────────────────────────────────────────────────

class _Sim:
    """Lightweight sim runner used for intro demos and NTV rounds."""

    def __init__(self, config, arena: dict):
        self._ev    = VehicleEvaluator(config)
        self._arena = arena
        rs          = arena.get("robot_start", {})
        self._robot = RobotState(
            x=rs.get("x", 0.0),
            y=rs.get("y", 0.0),
            heading=math.radians(rs.get("heading_deg", 90.0)),
        )
        self._trace: list = []
        self._accum = 0.0

    def tick(self, dt: float):
        self._accum += dt
        while self._accum >= PHYS_DT:
            self._accum -= PHYS_DT
            self._step(PHYS_DT)

    def _step(self, dt):
        ir_m = IR_CONFIGS["standard"]
        def ir(mount):
            wx, wy, wa = self._robot.sensor_world_pos(mount)
            return ir_reading(ray_distance(wx, wy, wa, self._arena, 0.5))
        def ldr(mount):
            wx, wy, _ = self._robot.sensor_world_pos(mount)
            illum = light_at(wx, wy, self._arena)
            if self._arena["light_sources"]:
                # Use actual illuminance — ambient floor would mask the gradient
                illum = max(0.05, illum)
            else:
                illum = 0.3   # no light sources: ambient floor
            return ldr_reading(illum)

        from engine.vehicle import SensorReadings
        sensors = SensorReadings(
            **{"IR·L": ir(ir_m[0]), "IR·R": ir(ir_m[1]),
               "LDR·C1": ldr(LDR_MOUNTS[0]),
               "LDR·C2": ldr(LDR_MOUNTS[1])})

        motors = self._ev.tick(sensors, dt)
        old_x, old_y = self._robot.x, self._robot.y
        self._robot.step(motors.left, motors.right, dt)

        aw = self._arena["width"]  / 2 - ROBOT_R
        ah = self._arena["height"] / 2 - ROBOT_R
        if (self._robot.x < -aw or self._robot.x > aw or
                self._robot.y < -ah or self._robot.y > ah):
            self._robot.x, self._robot.y = old_x, old_y

        for iw in self._arena.get("internal_walls", []):
            dx, dy = iw["x1"]-iw["x0"], iw["y1"]-iw["y0"]
            lsq = dx*dx + dy*dy
            if lsq < 1e-12:
                if math.hypot(self._robot.x-iw["x0"],
                              self._robot.y-iw["y0"]) < ROBOT_R:
                    self._robot.x, self._robot.y = old_x, old_y
                    break
                continue
            t = max(0.0, min(1.0,
                ((self._robot.x-iw["x0"])*dx +
                 (self._robot.y-iw["y0"])*dy) / lsq))
            if math.hypot(self._robot.x-(iw["x0"]+t*dx),
                          self._robot.y-(iw["y0"]+t*dy)) < ROBOT_R:
                self._robot.x, self._robot.y = old_x, old_y
                break

        self._trace.append((self._robot.x, self._robot.y))
        if len(self._trace) > 3000:
            self._trace = self._trace[-3000:]

    @property
    def robot(self): return self._robot
    @property
    def trace(self): return self._trace
    @property
    def arena(self): return self._arena

    def signal_snapshot(self) -> dict:
        """Return the last computed signal values from the evaluator."""
        return dict(self._ev.signal_snapshot())


# ── NTV Game ──────────────────────────────────────────────────────────────────

class NTVGame:

    def __init__(self, dlg_class, load_script_fn,
                 font_hd, font_md, font_sm,
                 has_theme: bool = False, theme=None,
                 window_size: tuple = (0, 0)):
        self._dlg_class    = dlg_class
        self._load_script  = load_script_fn
        self._font_hd      = font_hd
        self._font_md      = font_md
        self._font_sm      = font_sm
        self._has_theme    = has_theme
        self._T            = theme
        self._window_size   = window_size
        self._back_btn_rect = None

        self._rng          = random.Random()
        self._progress     = load_progress()
        self._score        = SessionScore()
        self._round_num       = 0
        self._round_seq       = RoundSequence(self._rng)
        self._current_round: Round | None = None
        self._round_question: str = QUESTION_VARIANTS[0]
        self._sim: _Sim | None = None
        self._demo_timer      = 0.0
        self._round_timer     = 0.0

        # Intro state
        self._intro_idx    = 0   # 0-4 = vehicles, 5 = task screen
        self._intro_arenas = [
            generate_arena(v.motive, self._rng)
            for v in INTRO_ORDER
        ]

        # Dialogue
        self._dlg          = None
        self._show_dlg     = False

        # Round answer state (dual-column)
        self._answer         = NTVAnswer()
        self._feedback_lines: list[str] = []
        self._round_done     = False
        self._pending_correct = 0.0

        # Tally delta flashes
        self._correct_flash  = 0.0   # seconds remaining for flash
        self._incorrect_flash = 0.0

        # State
        self._state = "intro_narrate_0"
        self._done  = False
        self._nav   = NavOverlay(back_destination="Valentino's Vehicles")

        # Vehicle demos removed — player already saw them in VV intro.
        # Always go straight to the task explanation.
        self._start_task_narration()

        self._btn_rects: dict = {}

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def is_done(self) -> bool:
        return self._done or self._nav.confirmed

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Nav overlay gets first priority when active
            if self._nav.is_active:
                if self._btn_rects.get("btn_back_ok",
                        pygame.Rect(0,0,0,0)).collidepoint(event.pos):
                    self._nav.confirm()
                elif self._btn_rects.get("btn_back_cancel",
                        pygame.Rect(0,0,0,0)).collidepoint(event.pos):
                    self._nav.cancel()
                return
            # Back button — direct hit-test on stored rect
            back_r = getattr(self, "_back_btn_rect", None)
            if back_r and back_r.collidepoint(event.pos):
                self._nav.request_back()
                return
            self._on_click(event.pos)
        elif event.type == pygame.KEYDOWN:
            if self._nav.handle_key(event.key):
                return
            self._on_key(event)

    def update(self, dt: float):
        """Called every frame with elapsed time in seconds."""
        # Dialogue tick
        if self._show_dlg and self._dlg and not self._dlg.is_done:
            self._dlg.update(dt)

        # Flash timers
        if self._correct_flash   > 0: self._correct_flash   -= dt
        if self._incorrect_flash > 0: self._incorrect_flash -= dt

        state = self._state

        # Intro demo
        if state.startswith("intro_demo_"):
            if self._sim:
                self._sim.tick(dt)
            self._demo_timer -= dt
            if self._demo_timer <= 0:
                self._advance_intro()

        # Round run
        elif state == "round_run":
            if self._sim:
                self._sim.tick(dt)
            self._round_timer -= dt
            if self._round_timer <= 0:
                self._state = "round_guess"
                # Keep sim alive — canvas needs it to show frozen end-state

    def draw(self, screen: pygame.Surface,
             canvas_rect: pygame.Rect,
             panel_x: int, panel_w: int,
             narr_rect: pygame.Rect, ctrl_rect: pygame.Rect):
        """Draw everything — canvas and panel."""
        self._btn_rects = {}
        self._draw_canvas(screen, canvas_rect)
        self._draw_controls(screen, ctrl_rect.x, ctrl_rect.width, ctrl_rect)
        self._draw_narrative(screen, narr_rect)

        # Back button — bottom-right corner, clamped to screen
        PAD = 6
        BW, BH = 60, 22
        scr_h   = screen.get_height()
        back_y  = min(narr_rect.bottom - BH - PAD, scr_h - BH - PAD)
        back_r  = pygame.Rect(
            narr_rect.right - BW - PAD,
            back_y,
            BW, BH)
        mx, my = pygame.mouse.get_pos()
        hov    = back_r.collidepoint(mx, my)
        import engine.theme as _T
        pygame.draw.rect(screen, _T.PANEL_DEEP, back_r, border_radius=3)
        pygame.draw.rect(screen, _T.PHOSPHOR_MID if hov else _T.BORDER,
                         back_r, 1, border_radius=3)
        lbl = self._font_sm.render("Back", True,
                                   _T.WHITE_GREEN if hov else _T.TEXT_DIM)
        screen.blit(lbl, (back_r.centerx - lbl.get_width()  // 2,
                          back_r.centery - lbl.get_height() // 2))
        self._back_btn_rect = back_r  # stored for direct hit-test in handle_event

        # Nav confirm overlay — drawn on top of everything
        if self._nav.is_active:
            self._nav.draw_overlay(
                screen, screen.get_width(), screen.get_height(),
                self._font_hd, self._font_sm, self._btn_rects)

    # ── Intro flow ─────────────────────────────────────────────────────────────

    def _start_intro_narration(self, idx: int):
        self._intro_idx = idx
        self._state     = f"intro_narrate_{idx}"
        self._show_dlg  = True
        script_names    = [
            "ntv_intro_v1", "ntv_intro_v2a", "ntv_intro_v2b",
            "ntv_intro_v3a", "ntv_intro_v3b",
        ]
        text = _load_script(script_names[idx])
        self._rebuild_dlg(text)

    def _start_intro_demo(self, idx: int):
        self._state      = f"intro_demo_{idx}"
        self._show_dlg   = False
        self._demo_timer = DEMO_SECS
        vdef   = INTRO_ORDER[idx]
        arena  = self._intro_arenas[idx]
        self._sim = _Sim(vdef.config, arena)

    def _advance_intro(self):
        idx = self._intro_idx + 1
        if idx < len(INTRO_ORDER):
            self._start_intro_narration(idx)
        else:
            self._state = "intro_task"
            self._start_task_narration()

    def _start_task_narration(self):
        self._state    = "intro_task"
        self._show_dlg = True
        text = _load_script("ntv_intro_task")
        self._rebuild_dlg(text)

    # ── Round flow ─────────────────────────────────────────────────────────────

    def _start_round(self):
        round_obj            = self._round_seq.next_round()
        self._round_num      = round_obj.number
        self._current_round  = round_obj
        self._answer         = NTVAnswer()
        self._feedback_lines = []
        self._round_done     = False
        self._pending_correct = 0.0
        self._sim            = _Sim(round_obj.config, round_obj.arena)
        self._round_timer    = round_obj.demo_timer
        self._state          = "round_run"
        self._show_dlg       = False
        self._round_question = self._rng.choice(QUESTION_VARIANTS)

    def _submit_guess(self):
        if not self._answer.is_complete:
            return
        r   = self._current_round
        res = r.evaluate(self._answer)

        if res["both_correct"]:
            self._score.correct  += 1
            self._correct_flash   = 1.2
            self._pending_correct = 1.0

        # Build feedback — show what the player guessed, mark right/wrong
        lines = []
        ldr_mark = "✓" if res["ldr_correct"] else "✗"
        ir_mark  = "✓" if res["ir_correct"]  else "✗"
        lines.append(f"{ldr_mark} LDR: {self._answer.ldr}")
        lines.append(f"{ir_mark} IR:  {self._answer.ir}")
        if res["both_correct"]:
            lines.append("Correct!")
        elif res["round_over"]:
            lines.append("See the correct answer below.")
        else:
            lines.append("Not quite.")
        self._feedback_lines = lines

        if res["round_over"]:
            self._finish_round(res)

        self._state = "round_result"

    def _finish_round(self, final_res: dict):
        self._round_done = True
        if not final_res["both_correct"]:
            self._score.incorrect   += 1
            self._incorrect_flash    = 1.2
        self._score.rounds += 1

    def _replay_round(self):
        """Restart the sim for the current round so player can rewatch."""
        if self._current_round is None:
            return
        self._sim = _Sim(self._current_round.config,
                         self._current_round.arena)
        self._round_timer = self._current_round.demo_timer
        self._state       = "round_run"

    def _open_wiring_view(self):
        """Open wiring editor in read-only inspection mode."""
        if self._current_round is None:
            return
        cfg = self._current_round.config

        from engine.builder.wiring_editor import WiringEditor
        sensor_names = ["LDR·C1", "LDR·C2",
                         "IR·L",   "IR·R"]
        motor_names  = ["FL", "FR"]
        editor = WiringEditor(
            initial_config=cfg,
            title="Vehicle Wiring — Read Only (press Esc to close)",
            sensor_names=sensor_names,
            motor_names=motor_names)
        result = editor.run()
        # Restore window to NTV dimensions
        ww, wh = self._window_size
        if ww > 0 and wh > 0:
            pygame.display.set_mode((ww, wh))
            pygame.display.set_caption("Valentino's Vehicles")
        pygame.event.clear()

    # ── Dialogue helper ────────────────────────────────────────────────────────

    def _rebuild_dlg(self, text: str):
        """Create a fresh DialogueBox with the given text."""
        try:
            self._dlg = self._dlg_class(300, 200, font_size=13)
        except TypeError:
            try:
                self._dlg = self._dlg_class(300, 200)
            except TypeError:
                self._dlg = self._dlg_class()
        self._dlg.load(text)

    # ── Input handling ─────────────────────────────────────────────────────────

    def _on_key(self, event):
        if self._show_dlg and self._dlg and not self._dlg.is_done:
            if event.key == pygame.K_SPACE:
                self._dlg.advance()
            elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                self._dlg.skip()
            return
        if event.key == pygame.K_ESCAPE:
            self._end_session()

    def _on_click(self, pos):
        # Don't advance dialogue if click is on a registered button
        for rect in self._btn_rects.values():
            if rect.collidepoint(pos):
                break
        else:
            # Click was not on any button — advance dialogue
            if self._show_dlg and self._dlg and not self._dlg.is_done:
                self._dlg.advance()
                return
        for name, rect in self._btn_rects.items():
            if rect.collidepoint(pos):
                self._handle_btn(name)
                return

    def _handle_btn(self, name: str):
        state = self._state

        # ── Intro ───────────────────────────────────────────────────────
        if name == "btn_start_game":
            mark_intro_seen()
            self._progress["intro_seen"] = True
            self._start_round()

        # ── Round guess ─────────────────────────────────────────────────
        elif name.startswith("btn_choice_"):
            idx = int(name.split("_")[-1])
            # btn_choice_ldr_N or btn_choice_ir_N
            pass  # handled by btn_ldr_* and btn_ir_* below

        elif name.startswith("btn_ldr_"):
            self._answer.ldr = name[len("btn_ldr_"):].replace("_", " ")

        elif name.startswith("btn_ir_"):
            self._answer.ir = name[len("btn_ir_"):].replace("_", " ")

        elif name == "btn_verify":
            if self._answer.is_complete:
                self._submit_guess()

        # ── Round result ─────────────────────────────────────────────────
        elif name == "btn_next_round":
            self._start_round()

        elif name == "btn_replay":
            self._replay_round()

        elif name == "btn_view_wiring":
            self._open_wiring_view()
            # Re-enter result state (wiring view is modal)
            self._state = "round_result"

        elif name == "btn_try_again":
            self._state  = "round_guess"
            self._answer = NTVAnswer()

        # ── Back ─────────────────────────────────────────────────────────
        elif name == "btn_back_menu":
            self._nav.request_back()
        elif name == "btn_back_ok":
            self._end_session()
            self._nav.confirm()
        elif name == "btn_back_cancel":
            self._nav.cancel()

    def _end_session(self):
        record_session(self._score.correct,
                       self._score.incorrect,
                       self._score.rounds)
        self._done = True

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _C(self, key: str):
        """Return colour from current engine.theme (always live)."""
        t = _get_T()
        if t:
            return getattr(t, key, _TEXT)
        # Phosphor fallback
        mapping = {
            "BG": _BG, "PANEL": _PANEL, "PANEL_DEEP": _PANEL_DEEP,
            "BORDER": _BORDER, "TEXT": _TEXT, "TEXT_DIM": _TEXT_DIM,
            "WHITE_GREEN": _WHITE_GREEN, "PHOSPHOR": _PHOSPHOR,
            "PHOSPHOR_MID": _PHOSPHOR_MID, "AMBER": _AMBER,
            "TEXT_BRIGHT": _TEXT_BRIGHT, "BEH_SEEK": _CYAN,
            "RED_PH": _RED,
        }
        return mapping.get(key, _TEXT)

    def _btn(self, surf, x, y, w, h, label, name,
             accent=False, disabled=False, color=None):
        rect  = pygame.Rect(x, y, w, h)
        self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov    = rect.collidepoint(mx, my) and not disabled
        if disabled:
            fill   = self._C("PANEL_DEEP")
            border = tuple(c//2 for c in self._C("BORDER"))
            tc     = self._C("TEXT_DIM")
        elif accent:
            fill   = color or (self._C("PHOSPHOR_MID") if hov
                               else self._C("PANEL_DEEP"))
            border = self._C("PHOSPHOR")
            tc     = self._C("WHITE_GREEN")
        else:
            fill   = color or (self._C("PANEL") if hov
                               else self._C("PANEL_DEEP"))
            border = self._C("BORDER")
            tc     = self._C("TEXT")
        pygame.draw.rect(surf, fill,   rect, border_radius=4)
        pygame.draw.rect(surf, border, rect, 1, border_radius=4)
        t = self._font_md.render(label, True, tc)
        surf.blit(t, (rect.centerx - t.get_width()//2,
                      rect.centery - t.get_height()//2))

    def _rule(self, surf, y, w, x=0):
        pygame.draw.line(surf, self._C("BORDER"), (x, y), (x + w, y))

    def _text_wrap(self, surf, text, x, y, w, font=None, col=None) -> int:
        font = font or self._font_sm
        col  = col  or _TEXT
        for word_line in text.split("\n"):
            words = word_line.split()
            line  = ""
            for word in words:
                test = (line + " " + word).strip()
                if font.size(test)[0] <= w:
                    line = test
                else:
                    if line:
                        surf.blit(font.render(line, True, col), (x, y))
                        y += font.get_linesize() + 2
                    line = word
            if line:
                surf.blit(font.render(line, True, col), (x, y))
                y += font.get_linesize() + 2
        return y

    # ── Canvas drawing ─────────────────────────────────────────────────────────

    def _draw_canvas(self, screen, cr: pygame.Rect):
        state = self._state

        if state.startswith("intro_demo_") and self._sim:
            draw_arena(screen, cr, self._sim.arena,
                       robot_states=[self._sim.robot],
                       traces={"robot": self._sim.trace})

        elif state.startswith("intro_"):
            # Show the static intro arena for the current vehicle
            idx   = min(self._intro_idx, len(INTRO_ORDER) - 1)
            arena = self._intro_arenas[idx]
            draw_arena(screen, cr, arena)

        elif state in ("round_run",) and self._sim:
            draw_arena(screen, cr, self._sim.arena,
                       robot_states=[self._sim.robot],
                       traces={"robot": self._sim.trace})

        elif state in ("round_guess", "round_result") and self._sim:
            # Show frozen end-state: trace + robot at final position
            draw_arena(screen, cr, self._sim.arena,
                       robot_states=[self._sim.robot],
                       traces={"robot": self._sim.trace})

        else:
            pygame.draw.rect(screen, self._C("BG"), cr)

        # Timer overlay during runs
        if state.startswith("intro_demo_"):
            self._draw_timer(screen, cr, self._demo_timer, DEMO_SECS)
        elif state == "round_run":
            timer_max = (self._current_round.demo_timer
                         if self._current_round else ROUND_SECS)
            self._draw_timer(screen, cr, self._round_timer, timer_max)

    def _draw_timer(self, screen, cr, remaining, total):
        frac  = max(0.0, remaining / total)
        bar_w = int(cr.width * frac)
        bar_r = pygame.Rect(cr.x, cr.bottom - 6, bar_w, 6)
        pygame.draw.rect(screen, self._C("PHOSPHOR_MID"), bar_r)

        t = self._font_sm.render(f"{remaining:.1f}s", True, self._C("TEXT_DIM"))
        screen.blit(t, (cr.right - t.get_width() - 8, cr.bottom - 20))

    # ── Control panel ──────────────────────────────────────────────────────────

    def _draw_controls(self, screen, x, w, ctrl_rect: pygame.Rect):
        state = self._state

        if state.startswith("intro_narrate_") or state == "intro_task":
            self._draw_ctrl_intro_narrate(screen, x, w, ctrl_rect)
        elif state.startswith("intro_demo_"):
            self._draw_ctrl_intro_demo(screen, x, w, ctrl_rect)
        elif state == "round_run":
            self._draw_ctrl_round_run(screen, x, w, ctrl_rect)
        elif state == "round_guess":
            self._draw_ctrl_round_guess(screen, x, w, ctrl_rect)
        elif state == "round_result":
            self._draw_ctrl_round_result(screen, x, w, ctrl_rect)


    def _draw_ctrl_intro_narrate(self, screen, x, w, ctrl_rect):
        y = ctrl_rect.y + 8

        # Title
        tt = self._font_hd.render("NAME THAT VEHICLE", True, self._C("WHITE_GREEN"))
        screen.blit(tt, (x, y)); y += 26
        self._rule(screen, y, w, x); y += 12

        # Which vehicle or task
        state = self._state
        if state == "intro_task":
            sub = self._font_sm.render("Game introduction", True, self._C("TEXT_DIM"))
        else:
            idx  = self._intro_idx
            vdef = INTRO_ORDER[idx]
            sub  = self._font_sm.render(
                f"Introducing: {vdef.label}", True, self._C("TEXT_DIM"))
        screen.blit(sub, (x, y)); y += 22

        # Tally display
        y = self._draw_tally(screen, x, w, ctrl_rect.bottom - 120)

        # Buttons at bottom
        btn_y = ctrl_rect.bottom - 80

        if state != "intro_task":
            # Show demo button (only active when narration is done)
            dlg_done = self._dlg is None or self._dlg.is_done
            self._btn(screen, x, btn_y, w, 34,
                      "▶  View Demo", "btn_view_demo",
                      accent=dlg_done, disabled=not dlg_done)
            btn_y += 44
        else:
            # Task screen — show Start Game button
            dlg_done = self._dlg is None or self._dlg.is_done
            self._btn(screen, x, btn_y, w, 34,
                      "▶  Start Game", "btn_start_game",
                      accent=dlg_done, disabled=not dlg_done)
            btn_y += 44



    def _draw_ctrl_intro_demo(self, screen, x, w, ctrl_rect):
        y   = ctrl_rect.y + 8
        idx = self._intro_idx
        tt  = self._font_hd.render("WATCH", True, self._C("WHITE_GREEN"))
        screen.blit(tt, (x, y)); y += 26
        self._rule(screen, y, w, x); y += 12

        vdef = INTRO_ORDER[idx]
        sub  = self._font_sm.render(vdef.full_name, True, self._C("AMBER"))
        screen.blit(sub, (x, y)); y += 20

        note = self._font_sm.render("Observing...", True, self._C("TEXT_DIM"))
        screen.blit(note, (x, y))


    def _draw_ctrl_round_run(self, screen, x, w, ctrl_rect):
        y = ctrl_rect.y + 8
        tt = self._font_hd.render("OBSERVE", True, self._C("WHITE_GREEN"))
        screen.blit(tt, (x, y)); y += 26
        self._rule(screen, y, w, x); y += 12

        rn  = self._font_sm.render(f"Round {self._round_num}", True, self._C("TEXT_DIM"))
        screen.blit(rn, (x, y)); y += 22

        note = self._font_sm.render("Watch carefully.", True, self._C("TEXT"))
        screen.blit(note, (x, y))

        self._draw_tally(screen, x, w, ctrl_rect.bottom - 80)

    def _draw_ctrl_round_guess(self, screen, x, w, ctrl_rect):
        """Dual-column answer UI: LDR column | IR column."""
        y = ctrl_rect.y + 8

        qt = self._font_md.render(
            self._round_question, True, self._C("WHITE_GREEN"))
        screen.blit(qt, (x, y)); y += 24
        self._rule(screen, y, w, x); y += 10

        # Two columns: LDR | IR
        col_w  = (w - 8) // 2
        col_x  = [x, x + col_w + 8]
        HDR    = [(self._C("AMBER"), "LDR"),
                  (self._C("PHOSPHOR"), "IR")]

        for ci, (hcol, hlbl) in enumerate(HDR):
            cx = col_x[ci]
            ht = self._font_sm.render(hlbl, True, hcol)
            screen.blit(ht, (cx, y))

        y += 18

        selected = [self._answer.ldr, self._answer.ir]
        prefixes = ["btn_ldr_", "btn_ir_"]
        col_sel  = [self._C("AMBER"), self._C("PHOSPHOR")]

        row_y = y
        for choice in COLUMN_CHOICES:
            for ci in range(2):
                cx  = col_x[ci]
                sel = (selected[ci] == choice)
                col = col_sel[ci] if sel else (60, 80, 60)
                bg  = self._C("PANEL") if sel else self._C("PANEL_DEEP")
                r   = pygame.Rect(cx, row_y, col_w, 26)
                pygame.draw.rect(screen, bg,  r, border_radius=3)
                pygame.draw.rect(screen, col, r, 1, border_radius=3)
                lbl = self._font_sm.render(
                    choice, True,
                    (220, 220, 180) if sel else (120, 140, 120))
                screen.blit(lbl, (cx + 6, row_y + 5))
                btn_name = prefixes[ci] + choice.replace(" ", "_")
                self._btn_rects[btn_name] = r
            row_y += 30

        row_y += 4
        can_verify = self._answer.is_complete
        self._btn(screen, x, row_y, w, 34, "Verify", "btn_verify",
                  accent=can_verify, disabled=not can_verify)

        self._draw_tally(screen, x, w, ctrl_rect.bottom - 52)

    def _draw_ctrl_round_result(self, screen, x, w, ctrl_rect):

        y = ctrl_rect.y + 8

        # Feedback
        for line in self._feedback_lines:
            col = _PHOSPHOR if line.startswith("✓") else \
                  (_RED if line.startswith("✗") else _TEXT)
            y   = self._text_wrap(screen, line, x, y, w,
                                  self._font_sm, col)
            y  += 4

        self._rule(screen, y, w, x); y += 10

        r = self._current_round
        if r and r.round_over:
            # Correct answer reveal
            ldr_ans = r.correct_ldr
            ir_ans  = r.correct_ir
            al = self._font_sm.render(
                f"LDR: {ldr_ans}  |  IR: {ir_ans}",
                                      True, _AMBER)
            screen.blit(al, (x, y)); y += 20

            self._btn(screen, x, y, w, 30,
                      "↺  Replay", "btn_replay")
            y += 36
            self._btn(screen, x, y, w, 30,
                      "View Wiring", "btn_view_wiring")
            y += 36
            self._btn(screen, x, y, w, 34,
                      "Next Vehicle  →", "btn_next_round", accent=True)
        else:
            # Not done yet — replay and try again
            guesses_left = 3 - r.guesses_made if r else 0
            gl = self._font_sm.render(
                f"{guesses_left} guess{'es' if guesses_left != 1 else ''} remaining",
                True, _TEXT_DIM)
            screen.blit(gl, (x, y)); y += 20

            self._btn(screen, x, y, w, 30,
                      "↺  Replay", "btn_replay")
            y += 36
            self._btn(screen, x, y, w, 34,
                      "Try Again  ↺", "btn_try_again", accent=True)

        self._draw_tally(screen, x, w, ctrl_rect.bottom - 52)

    def _draw_tally(self, screen, x, w, y) -> int:
        """Draw score tally. Returns y after drawing."""
        self._rule(screen, y, w, x); y += 6
        prog  = load_progress()
        lt_c  = prog.get("lifetime_correct",   0.0)
        lt_i  = prog.get("lifetime_incorrect",  0.0)

        # Session tally
        cc = self._C("PHOSPHOR") if self._correct_flash   > 0 else _TEXT_DIM
        ic = self._C("RED_PH")   if self._incorrect_flash > 0 else _TEXT_DIM

        sc = self._font_sm.render(
            f"Session  ✓ {self._score.correct:.1f}  "
            f"✗ {self._score.incorrect:.1f}  "
            f"#{self._score.rounds}",
            True, _TEXT_DIM)
        screen.blit(sc, (x, y)); y += 16

        lc = self._font_sm.render(
            f"Lifetime ✓ {lt_c:.1f}  ✗ {lt_i:.1f}",
            True, _TEXT_DIM)
        screen.blit(lc, (x, y)); y += 14
        return y

    # ── Narrative region ────────────────────────────────────────────────────────

    def _draw_narrative(self, screen, narr_rect: pygame.Rect):
        pygame.draw.rect(screen, self._C("PANEL_DEEP"), narr_rect)
        if self._show_dlg and self._dlg and not self._dlg.is_done:
            # Update dialogue box dimensions to match current narr_rect
            self._dlg._w = narr_rect.width
            self._dlg._h = narr_rect.height
            self._dlg.draw(screen, narr_rect.x, narr_rect.y)
        else:
            hint = self._font_sm.render(
                "Space / click to advance",
                True, _TEXT_DIM)
            if self._show_dlg:
                # Dialogue done — show replay hint
                hint2 = self._font_sm.render("", True, self._C("TEXT_DIM"))
                screen.blit(hint2, (narr_rect.x + 6,
                                    narr_rect.y + 6))
