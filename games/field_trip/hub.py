"""
games/field_trip/hub.py
------------------------
Field Trip — Virtual field navigation game.

States:
    welcome          PAW-Bot intro
    tutorial_attractor  Guided attractor task
    tutorial_repulsor   Guided repulsor task
    tutorial_complete   PAW-Bot celebration → challenge loop
    challenge_build  Player builds robot (robot builder left, arena preview right)
    challenge_run    Simulation running
    challenge_result Win/lose result + cog award
    challenge_done   All challenges complete

Layout (own window, not using valentinos Layout):
    Left  (PANEL_W): controls + narrative
    Right (rest):    arena preview / simulation canvas
"""

from __future__ import annotations
import math, os, sys, time, random, copy
import pygame

ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
GAMES    = os.path.join(ROOT, "games")
GAME_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, GAMES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine.theme as T
T.apply(T.load_saved_theme())

from engine.layout                  import Layout
from engine.professor               import DialogueBox, load_script
from engine.nav                     import NavOverlay
from engine.robot_body              import RobotState, SensorMount
from engine.sensor_physics          import ir_reading, ldr_reading
from engine.field_trip.field_physics import (
    FieldSensor, FieldSource, ATTRACT, REPEL,
    compute_force, force_to_motors,
    check_reach_light, check_reach_wall, check_repulsor_contact,
    _nearest_point_on_segment,
    RepulsorContact,
)
from engine.field_trip.challenges   import (
    Challenge, ALL_CHALLENGES, generate_challenge,
)
from engine.arena import draw_arena, world_to_screen, arena_scale

# ── Constants ─────────────────────────────────────────────────────────────────

PANEL_W       = 440
PHYS_DT       = 1 / 60
CYCLE_S       = 0.5        # one "loop cycle" duration for repulsor grace
GRACE_CYCLES  = 3          # grace cycles per active repulsor (legacy)
STUCK_RADIUS_M = 0.03      # 'stuck' if robot stays within this radius...
STUCK_FAIL_S   = 4.0       # ...for this many seconds (touching walls is OK;
                           #    only being TRAPPED in one spot fails you)
from engine.field_trip.challenges import BODY_RADIUS   # 0.0775 — see challenges.py
from engine.builder.robot_builder import CHASSIS, chassis_collision_radius
WHEEL_BASE    = 0.080      # m, left-to-right wheel separation (robots/ethology_v2.json).
                           # NOT the body width: the old code used BODY_RADIUS*2
                           # = 0.155 here, so Field Trip simulated a robot that
                           # turned at about half the real rate.
MOTOR_SPEED_LEGACY = 0.25
MOTOR_SPEED   = 0.35       # m/s at full command — hardware max (robot_model.py)
ORBIT_INWARD  = 0.3        # small toward-source radial baked into Orbit so the
                           # ring is stable (pure tangential drifts outward)

# Cog thresholds: attempts used to determine cog award
COG_GOLD   = 1   # solved on first attempt
COG_SILVER = 3   # solved within 3 attempts
COG_BRONZE = 0   # solution shown or barely passed


def _font_hd(): return pygame.font.SysFont("monospace", 22, bold=True)
def _font_md(): return pygame.font.SysFont("monospace", 16)
def _font_sm(): return pygame.font.SysFont("monospace", 13)


# ── Simulation ─────────────────────────────────────────────────────────────────

class _Sim:
    """Runs one Field Trip challenge physics step."""

    def __init__(self, challenge: Challenge,
                 sensors: list[FieldSensor],
                 chassis_spec: dict | None = None):
        self.challenge   = challenge
        self.sensors     = sensors
        self.chassis_spec = chassis_spec or {}
        rs              = challenge.arena.get("robot_start", {})
        self.robot      = RobotState(
            x            = rs.get("x", 0.0),
            y            = rs.get("y", -0.30),
            heading      = math.radians(rs.get("heading_deg", 90.0)),
            chassis_spec = self.chassis_spec,
        )
        self.trace: list[tuple[float,float]] = []
        self.elapsed    = 0.0
        self.success    = False
        self.failure    = False
        self.fail_reason= ""
        # Repulsor grace tracking: {source_id: RepulsorContact}
        self._contacts: dict[str, RepulsorContact] = {}
        self._stuck_anchor = None   # (x,y) dwell anchor for stuck detection
        self._stuck_time   = 0.0
        self._cycle_acc = 0.0   # accumulates time toward next cycle tick
        self._dwell_acc = 0.0   # continuous time held inside the dwell zone

        # ── Physics ───────────────────────────────────────────────────────────
        # Rigid-body contact against the CHASSIS OUTLINE, shared with Robot
        # Ethology and Valentino's. Replaces a hand-rolled circle test that
        # (a) used one radius for every chassis, (b) derived the wheelbase from
        # the body radius (0.155 where the real figure is 0.080), and (c) could
        # not represent a corner catching a wall.
        from engine.config import ArenaConfig, RobotConfig
        from engine.adapters.pybullet_drive import PyBulletAdapter
        spec = self.chassis_spec or CHASSIS["octagon"]
        self._robot_cfg = RobotConfig.from_dict({
            "body_radius":   chassis_collision_radius(spec),
            "wheel_base":    WHEEL_BASE,
            "total_mass_kg": 0.8,
            "chassis_spec":  spec,
        })
        self._physics = PyBulletAdapter(
            ArenaConfig.from_dict(challenge.arena), self._robot_cfg)
        self._physics.reset_robot(self.robot.x, self.robot.y, self.robot.heading)

    def _blocked(self, x: float, y: float) -> bool:
        """True if the robot BODY at (x, y) would penetrate a wall.

        Tests the arena boundary and every internal wall segment, using
        BODY_RADIUS so the body edge — not just the centre — is stopped at
        the wall face. Internal walls are treated as solid: the robot can
        touch the face (so 'reach the wall' challenges still register) but
        cannot pass through it. Repulsor avoid-penalties are unaffected and
        still applied separately in tick().
        """
        arena = self.challenge.arena
        aw = arena["width"]  / 2 - BODY_RADIUS
        ah = arena["height"] / 2 - BODY_RADIUS
        if x < -aw or x > aw or y < -ah or y > ah:
            return True
        # Block when the body edge reaches the wall SURFACE. The wall is a segment
        # with a real thickness, so the solid boundary is (BODY_RADIUS + wall
        # half-thickness) from the centerline — NOT just BODY_RADIUS. The old code
        # blocked at BODY_RADIUS-0.004 (ignoring thickness), which left a ~1.5cm
        # skin where the body overlapped the wall but wasn't stopped — letting the
        # robot slip OVER the wall near its ends/faces. We now block at the true
        # surface (minus a 4mm reach skin so 'reach the wall' still registers —
        # check_reach_wall uses the same body_radius+half_thickness threshold).
        for iw in arena.get("internal_walls", []):
            ax, ay, bx, by = iw["x0"], iw["y0"], iw["x1"], iw["y1"]
            half_t = iw.get("thickness", 0.025) / 2.0
            block_d = BODY_RADIUS + half_t - 0.004
            dx, dy = bx - ax, by - ay
            seg_sq = dx * dx + dy * dy
            if seg_sq < 1e-12:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg_sq))
            px, py = ax + t * dx, ay + t * dy
            if math.hypot(x - px, y - py) < block_d:
                return True
        return False

    def tick(self, dt: float) -> None:
        if self.success or self.failure:
            return
        self.elapsed += dt
        self._cycle_acc += dt

        arena   = self.challenge.arena
        sources = self.challenge.sources

        # Compute force and update robot position
        fx, fy = compute_force(
            self.sensors, sources,
            self.robot.x, self.robot.y, self.robot.heading,
            arena)

        left, right = force_to_motors(fx, fy, self.robot.heading)

        # Hand the motor command to the shared physics adapter and let rigid-body
        # contact decide what happens. `dt` is the PRIMITIVE DURATION — how long
        # this command is held before the next decision — mirroring the
        # firmware's driveProportional(left, right, durationInSeconds).
        #
        # Sliding along a wall is no longer hand-coded: a polygon body slides,
        # catches on a corner and torques itself square against a face on its
        # own, which the old per-axis fallback could not represent.
        self._physics.step(left, right, dt)
        new_x, new_y, heading = self._physics.get_pose()
        self.robot = RobotState(
            x=new_x, y=new_y, heading=heading,
            chassis_spec=self.chassis_spec)
        self.trace.append((self.robot.x, self.robot.y))
        if len(self.trace) > 4000:
            self.trace = self.trace[-4000:]

        # Check success (required_reach)
        for sid in self.challenge.required_reach:
            src = self.challenge.source_by_id(sid)
            if src is None:
                continue
            if src.stype == "light":
                if check_reach_light(self.robot.x, self.robot.y,
                                     BODY_RADIUS, src):
                    self.success = True
                    return
            else:
                if check_reach_wall(self.robot.x, self.robot.y,
                                    BODY_RADIUS, src):
                    self.success = True
                    return

        # Check repulsor contacts (grace period per cycle)
        if self._cycle_acc >= CYCLE_S:
            self._cycle_acc -= CYCLE_S
            # (1) AVOIDANCE: keep the original repulsor-contact rule for things the
            # challenge says to avoid (e.g. a forbidden light). Per design we now
            # allow WALLS to be touched, so wall-type avoid targets are exempt from
            # the contact-fail — only non-wall avoid targets (lights) still fail on
            # prolonged contact.
            active_now = set()
            for sid in self.challenge.required_avoid:
                src = self.challenge.source_by_id(sid)
                if not src:
                    continue
                if getattr(src, "stype", None) == "wall":
                    continue  # touching walls is allowed now
                if check_repulsor_contact(
                        self.robot.x, self.robot.y, BODY_RADIUS, src):
                    active_now.add(sid)
            for sid in active_now:
                if sid not in self._contacts:
                    self._contacts[sid] = RepulsorContact(sid, GRACE_CYCLES)
                else:
                    if not self._contacts[sid].tick():
                        self.failure = True
                        self.fail_reason = f"Too close to {sid} for too long"
                        return
            for sid in list(self._contacts):
                if sid not in active_now:
                    del self._contacts[sid]

            # (2) STUCK-IN-PLACE: only fails a robot that is genuinely TRAPPED —
            # not moving out of a small area for a sustained time — AND only when
            # the challenge has walls to get stuck against. This lets the robot
            # brush/slide along walls freely (per design) while still catching true
            # local-minimum traps. It does NOT fire while the robot is progressing
            # or holding a legitimate goal (goal-holding is near the TARGET, which
            # is a win, evaluated before this point).
            has_walls = bool(self.challenge.arena.get("internal_walls"))
            if has_walls and not self.success:
                px, py = self.robot.x, self.robot.y
                if self._stuck_anchor is None:
                    self._stuck_anchor = (px, py); self._stuck_time = 0.0
                else:
                    ax, ay = self._stuck_anchor
                    if math.hypot(px - ax, py - ay) <= STUCK_RADIUS_M:
                        self._stuck_time += CYCLE_S
                        if self._stuck_time >= STUCK_FAIL_S:
                            self.failure = True
                            self.fail_reason = "Stuck against the wall too long"
                            return
                    else:
                        self._stuck_anchor = (px, py); self._stuck_time = 0.0

        # Region-dwell win: hold distance-to-target within [inner, outer] for
        # hold_s continuously. Used by Orbit (annulus), keep-away (stay out),
        # and reach-and-remain (stay in). Resets if the robot leaves the band.
        dz = self.challenge.dwell_zone
        if dz:
            # Target may be a source id, OR an explicit position "pos": (x, y) —
            # the latter lets a walls-only maze use a LOCATION as the goal (e.g.
            # "reach the corner" in the spiral), with no light needed.
            tgt = self.challenge.source_by_id(dz["target"]) if dz.get("target") else None
            d = None
            if tgt is not None:
                if tgt.stype == "light":
                    d = math.hypot(self.robot.x - tgt.x, self.robot.y - tgt.y)
                else:
                    nx, ny = _nearest_point_on_segment(
                        self.robot.x, self.robot.y,
                        tgt.x0, tgt.y0, tgt.x1, tgt.y1)
                    d = math.hypot(self.robot.x - nx, self.robot.y - ny)
            elif dz.get("pos") is not None:
                gx, gy = dz["pos"]
                d = math.hypot(self.robot.x - gx, self.robot.y - gy)
            if d is not None and dz["inner"] <= d <= dz["outer"]:
                self._dwell_acc += dt
                if self._dwell_acc >= dz["hold_s"]:
                    self.success = True
                    return
            elif d is not None:
                self._dwell_acc = 0.0   # left the band — start over

        # Timeout (avoid-only challenges)
        if (not self.challenge.required_reach and not self.challenge.dwell_zone
                and self.elapsed >= self.challenge.duration_s):
            self.success = True

        # Hard timeout. Dwell challenges get a generous window (approach +
        # several hold attempts) and fail only if never held long enough.
        if self.challenge.dwell_zone:
            limit = self.challenge.dwell_zone.get("hold_s", 8.0) * 4 + 10.0
            if self.elapsed >= limit:
                self.failure    = True
                self.fail_reason = "Could not hold the zone in time"
        elif self.elapsed >= self.challenge.duration_s * 2:
            self.failure    = True
            self.fail_reason = "Time limit exceeded"


# ── Cog scoring ───────────────────────────────────────────────────────────────

class CogScore:
    def __init__(self):
        self.total      = 0
        self.streak     = 0   # consecutive gold runs
        self.history: list[int] = []   # cog count per challenge

    def award(self, cogs: int) -> None:
        self.total += cogs
        self.history.append(cogs)
        if cogs == 3:
            self.streak += 1
        else:
            self.streak = 0

    def cog_label(self, cogs: int) -> str:
        if cogs == 3: return "Gold"
        if cogs == 2: return "Silver"
        return "Bronze"

    def cog_color(self, cogs: int) -> tuple:
        if cogs == 3: return (255, 210, 0)
        if cogs == 2: return (180, 180, 180)
        return (180, 100, 40)


# ── Hub ───────────────────────────────────────────────────────────────────────

class Hub:

    def __init__(self):
        pygame.init()
        ww, wh = Layout.compute_window_size(0.90)
        self._ww = ww
        self._wh = wh
        self._screen = pygame.display.set_mode((ww, wh))
        pygame.display.set_caption("Field Trip")
        self._clock  = pygame.time.Clock()
        self._fhd    = _font_hd()
        self._fmd    = _font_md()
        self._fsm    = _font_sm()

        self._dlg    = DialogueBox(PANEL_W - 20, wh // 3,
                                   font_size=13, highlight_terms=True)
        self._nav    = NavOverlay(back_destination="PAW Robotics")
        self._score  = CogScore()
        self._state  = "welcome"
        self._show_dlg = True
        self._glossary_cache = None

        # Challenge state
        self._challenge_idx  = 0
        self._generated: dict[int, Challenge] = {}   # cache for stage-4 arenas
        self._attempts       = 0
        self._nudge_shown    = False
        self._solution_shown = False
        self._last_cogs      = 0
        self._show_jump_input = False
        self._jump_input_str  = ""
        self._sim: _Sim | None = None
        self._dbg_swirl = 0.0   # DEBUG (throwaway): live swirl readout value
        self._sensors: list[FieldSensor] = []
        self._robot_cfg: dict = {}

        # Tutorial phases
        self._tut_phase = 0   # 0=attractor, 1=repulsor, 2=complete

        self._load_welcome()

    # ── Script loading ────────────────────────────────────────────────────────

    def _load_script(self, name: str, fallback: str = "") -> None:
        txt = load_script("field_trip", name, fallback=fallback)
        self._dlg.load(txt)
        self._show_dlg = True

    def _load_c0_intro(self) -> bool:
        """Load the C0 franchise intro (ft_c0.txt @intro) into the dialogue."""
        self._glossary_cache = None
        slots = self._ft_script_slots("ft_c0")
        text = slots.get("intro")
        if not text:
            return False
        self._dlg.set_glossary(self._ft_glossary_defs())
        self._dlg.load(text)
        self._show_dlg = True
        return True

    def _ft_script_dir(self) -> str:
        """FT's own scripts directory. The shared professor.SCRIPTS_DIR is
        computed from professor.py's location and resolves to <repo>/scripts,
        which is NOT where FT's scripts live — so resolve relative to this
        game instead."""
        import os as _os
        return _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "scripts", "field_trip")

    def _ft_glossary_defs(self) -> dict:
        """Load footnote definitions {n: text} from the glossary script file."""
        if getattr(self, "_glossary_cache", None):
            return self._glossary_cache
        import re as _re, os as _os
        defs = {}
        try:
            path = _os.path.join(self._ft_script_dir(), "ft_glossary.txt")
            with open(path, encoding="utf-8") as f:
                for line in f:
                    m = _re.match(r'\((\d+)\)[^:]+:\s*(.*)', line.strip())
                    if m:
                        defs[int(m.group(1))] = m.group(2)
        except Exception:
            pass
        self._glossary_cache = defs
        return defs

    def _ft_script_slots(self, script_name: str) -> dict:
        """Parse an @slot-delimited narration script into {slot: text}."""
        import os as _os
        slots = {}
        try:
            path = _os.path.join(self._ft_script_dir(), script_name + ".txt")
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            return slots
        cur, buf = None, []
        for line in raw.splitlines():
            if line.startswith("@"):
                if cur is not None:
                    slots[cur] = "\n".join(buf).strip()
                cur, buf = line[1:].strip(), []
            else:
                buf.append(line)
        if cur is not None:
            slots[cur] = "\n".join(buf).strip()
        return slots

    def _load_narration(self, slot: str, with_glossary: bool = False) -> bool:
        """Show a narration slot for the current challenge from its script
        file (ft_c<N>.txt). Footnote definitions come from the glossary file;
        the box renders *term*(n) highlight-only and <term>(n) highlight+
        footnote. Returns True if anything was shown. Non-tutorial challenges
        (no script) show nothing."""
        idx = self._challenge_idx
        # Map by the challenge's OWN id (c04 -> ft_c4), NOT its position in the
        # sequence. Position-based mapping broke when c03 was deferred: every
        # later challenge loaded the previous one's script (off by one).
        cid = self._current_challenge().id            # e.g. "c04"
        num = int("".join(ch for ch in cid if ch.isdigit()))
        script_name = f"ft_c{num}"                    # c04 -> ft_c4
        slots = self._ft_script_slots(script_name)
        text = slots.get(slot)
        if not text:
            return False
        self._dlg.set_glossary(self._ft_glossary_defs())
        self._dlg.load(text)
        self._show_dlg = True
        return True

    # ── State transitions ─────────────────────────────────────────────────────

    def _load_welcome(self) -> None:
        self._state = "welcome"
        self._load_script("ft_welcome",
            fallback=(
                "PAW-BOT: Ready for a Field Trip? Press Start when you are."))

    def _load_challenge_for_tutorial(self, idx: int) -> None:
        self._challenge_idx = idx
        self._start_build()

    def _start_build(self) -> None:
        self._state        = "challenge_build"
        self._sim          = None
        self._sensors      = []
        # Note: _robot_cfg intentionally NOT reset here so edits persist
        # Tutorial narration: show the challenge intro (with glossary) the
        # first time we build it; the build_hint on later attempts. Non-tutorial
        # challenges have no narration, so nothing shows and play is unchanged.
        if self._attempts == 0 and self._load_narration("intro",
                                                        with_glossary=True):
            pass
        elif not self._load_narration("build_hint"):
            self._show_dlg = False

    def _start_run(self) -> None:
        self._state    = "challenge_run"
        self._attempts += 1
        challenge    = self._current_challenge()
        chassis_spec = self._robot_cfg.get("chassis_spec", {})
        self._sim    = _Sim(challenge, self._sensors, chassis_spec)
        if not self._load_narration("on_run"):
            self._show_dlg = False

    def _finish_run(self) -> None:
        assert self._sim is not None
        won = self._sim.success
        self._state = "challenge_result"

        if won:
            if self._attempts == 1:
                self._last_cogs = 3
            elif self._attempts <= 3:
                self._last_cogs = 2
            else:
                self._last_cogs = 1
            self._score.award(self._last_cogs)
        else:
            self._last_cogs = 0

        # Tutorial narration on the result screen: success or retry line.
        if not self._load_narration("success" if won else "retry"):
            self._show_dlg = False

    def _next_challenge(self) -> None:
        self._challenge_idx += 1
        self._attempts       = 0
        self._nudge_shown    = False
        self._solution_shown = False
        if self._challenge_idx >= len(ALL_CHALLENGES) + 50:
            self._state = "challenge_done"
        else:
            self._start_build()

    def _current_challenge(self) -> Challenge:
        idx = self._challenge_idx
        if idx < len(ALL_CHALLENGES):
            return ALL_CHALLENGES[idx]
        # Procedural (stage 4+) challenges must be STABLE. This method is called
        # from the draw loop, so generating on every call re-rolled the arena every
        # frame — goals visibly cycling and the challenge unplayable. Generate once
        # per index, from a seed derived from that index, and cache it: the same
        # challenge number always yields the same arena, within a session and across
        # runs.
        cached = self._generated.get(idx)
        if cached is None:
            cached = generate_challenge(idx + 1, random.Random(idx + 1))
            self._generated[idx] = cached
        return cached

    def _chassis_spec_from_cfg(self, robot_cfg: dict) -> dict:
        return robot_cfg.get("chassis_spec",
                             {"type": "rectangle",
                              "width_m": 0.094, "length_m": 0.167})

    def _build_sensors_from_cfg(self, robot_cfg: dict) -> list[FieldSensor]:
        sensors = []
        for sid, pos in robot_cfg.get("sensors", {}).items():
            stype   = pos.get("type", "LDR")
            channel = pos.get("channel", "W")
            tangential = float(pos.get("tangential", 0.0))
            # Radial response: attract (+1), repel (-1), or none. For 'none'
            # WITH circulation (an Orbit), apply a small inward bias so the
            # ring is stable — pure tangential drifts outward. ORBIT_INWARD is
            # a small toward-the-source magnitude (positive = inward).
            _pol = pos.get("policy", "attract")
            if _pol == "none":
                policy = ORBIT_INWARD if abs(tangential) > 1e-6 else 0.0
            else:
                policy = {"attract": ATTRACT, "repel": REPEL}.get(_pol, ATTRACT)
            sensors.append(FieldSensor(
                sensor_id  = sid,
                stype      = stype,
                channel    = channel,
                x_m        = pos.get("x_m", 0.0),
                y_m        = pos.get("y_m", 0.0),
                angle_deg  = pos.get("angle_deg", 0.0),
                policy     = policy,
                tangential = tangential,
            ))
        return sensors

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        accum = 0.0
        t_prev = time.monotonic()

        while True:
            t_now  = time.monotonic()
            dt_raw = t_now - t_prev
            t_prev = t_now
            dt     = min(dt_raw, 0.05)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                self._handle_event(event)

            # Dialogue typewriter tick
            if self._show_dlg and self._dlg:
                self._dlg.update(dt)

            # Physics
            if self._state == "challenge_run" and self._sim:
                accum += dt
                while accum >= PHYS_DT:
                    self._sim.tick(PHYS_DT)
                    accum -= PHYS_DT
                if self._sim.success or self._sim.failure:
                    self._finish_run()

            self._draw()
            pygame.display.flip()
            self._clock.tick(60)

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_event(self, event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            # Nav back button
            back_r = self._back_btn_rect()
            if back_r.collidepoint(pos):
                self._nav.request_back()
                return
            if self._nav.is_active:
                self._handle_nav_click(pos)
                return
            # Dialogue paging (click narrative area). Left third = back,
            # the rest = forward — large tap targets, matching << / >> .
            narr = self._narr_rect()
            if narr.collidepoint(pos) and self._show_dlg and self._dlg:
                if pos[0] < narr.x + narr.width // 3 and self._dlg.has_prev:
                    self._dlg.retreat()
                elif not self._dlg.is_done:
                    self._dlg.advance()
                elif self._state == "tutorial_intro":
                    # C0 intro finished — proceed into the first challenge.
                    self._start_build()
                return
            # When the C0 intro dialogue is finished, a click ANYWHERE (not just
            # inside the narration box) proceeds into the first challenge. Without
            # this, a click on the empty canvas did nothing and the screen looked
            # frozen/blank between the intro and the first challenge.
            if (self._state == "tutorial_intro" and self._show_dlg
                    and self._dlg and self._dlg.is_done):
                self._start_build()
                return
            # Button clicks
            self._handle_btn_click(pos)

        elif event.type == pygame.MOUSEBUTTONUP:
            if self._nav.is_active:
                return

        elif event.type == pygame.KEYDOWN:
            if self._nav.handle_key(event.key):
                if self._nav.confirmed:
                    return   # main loop will exit on next draw
                return

            # Narration paging via arrow keys (when dialogue is showing).
            if self._show_dlg and self._dlg:
                if event.key in (pygame.K_RIGHT, pygame.K_SPACE) \
                        and not self._dlg.is_done:
                    self._dlg.advance(); return
                if event.key == pygame.K_LEFT and self._dlg.has_prev:
                    self._dlg.retreat(); return

            # ── DEBUG (throwaway): live-tune tangential 'swirl' during a run ──
            # '[' / ']' decrease / increase the tangential gain on every
            # non-attractor sensor; '\' zeroes it.  Lets you FEEL the flow
            # parameter without the real UI.  Remove once the glyph UI lands.
            if self._state == "challenge_run" and self._sim:
                _delta = 0.0
                if event.key == pygame.K_RIGHTBRACKET:   _delta = +0.2
                elif event.key == pygame.K_LEFTBRACKET:  _delta = -0.2
                elif event.key == pygame.K_BACKSLASH:
                    for s in self._sim.sensors:
                        s.tangential = 0.0
                    self._dbg_swirl = 0.0
                    return
                if _delta:
                    for s in self._sim.sensors:
                        # only swirl sensors that aren't pure attractors,
                        # so Seek targets keep homing in
                        if s.policy != ATTRACT:
                            s.tangential = round(s.tangential + _delta, 2)
                    # remember last set value for the on-screen readout
                    self._dbg_swirl = round(
                        getattr(self, "_dbg_swirl", 0.0) + _delta, 2)
                    return

    def _handle_nav_click(self, pos) -> None:
        ok_r     = pygame.Rect(self._ww//2 - 60, self._wh//2 + 20, 120, 36)
        cancel_r = pygame.Rect(self._ww//2 - 60, self._wh//2 + 64, 120, 36)
        if ok_r.collidepoint(pos):
            self._nav.confirm()
        elif cancel_r.collidepoint(pos):
            self._nav.cancel()

    def _handle_btn_click(self, pos) -> None:
        for name, rect in self._btn_rects.items():
            if rect.collidepoint(pos):
                self._on_btn(name)
                return

    def _on_btn(self, name: str) -> None:
        if name == "btn_start":
            # Show the C0 franchise intro (narration only), then proceed to C1
            # build. C0 has no arena; it's PAW-BOT setting the stage.
            self._challenge_idx = 0
            self._attempts      = 0
            self._glossary_cache = None
            if self._load_c0_intro():
                self._state = "tutorial_intro"
            else:
                self._start_build()

        elif name == "btn_build":
            self._start_build()

        elif name == "btn_open_builder":
            self._open_robot_builder()

        elif name == "btn_run":
            if self._robot_cfg:
                self._sensors = self._build_sensors_from_cfg(self._robot_cfg)
                self._start_run()

        elif name == "btn_stop":
            if self._sim:
                self._sim.failure    = True
                self._sim.fail_reason = "Stopped"
            self._finish_run()

        elif name == "btn_jump_challenge":
            self._show_jump_input = not getattr(self, "_show_jump_input", False)

        elif name == "btn_next":
            if self._state == "challenge_result":
                self._next_challenge()

        elif name == "btn_retry":
            self._start_build()

        elif name == "btn_nudge":
            ch = self._current_challenge()
            self._load_script("", fallback=ch.hint)
            self._nudge_shown = True

        elif name == "btn_solution":
            ch = self._current_challenge()
            self._solution_shown = True
            self._last_cogs      = 1
            if ch.solution_file:
                # Load solution robot config and open builder
                import json as _json
                _sol_path = os.path.join(
                    GAME_DIR, "solutions", ch.solution_file)
                if os.path.exists(_sol_path):
                    self._robot_cfg = _json.load(open(_sol_path))
                    self._load_script("", fallback=
                        f"Solution loaded: {ch.solution_desc}\n\n"
                        "Press Build Robot to examine it, "
                        "then Run to see it in action.")
                else:
                    self._load_script("", fallback=ch.solution_desc)
            else:
                self._load_script("", fallback=ch.solution_desc)

    # ── Robot builder integration ──────────────────────────────────────────────

    def _open_robot_builder(self) -> None:
        from engine.builder.robot_builder import RobotBuilder
        # Default robot.json for Field Trip uses octagon chassis
        # Use saved robot_cfg if available, otherwise octagon default
        existing = self._robot_cfg if self._robot_cfg else {
            "chassis": "octagon",
            "sensors": {},
            "motors":  {},
        }
        ch       = self._current_challenge()
        builder  = RobotBuilder(existing_robot=existing,
                                initial_chassis="octagon",
                                show_wiring=False,
                                flow_styles=True,
                                radial_only=True,
                                window_size=(self._ww, self._wh),
                                arena_preview=ch.arena)
        result = builder.run()
        # Restore window
        self._screen = pygame.display.set_mode((self._ww, self._wh))
        pygame.display.set_caption("Field Trip")
        pygame.event.clear()
        if result is not None:
            # RobotBuilder returns (robot_cfg_dict, VehicleConfig)
            robot_cfg = result[0] if isinstance(result, tuple) else result
            if robot_cfg and isinstance(robot_cfg, dict):
                self._robot_cfg = robot_cfg

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _panel_rect(self) -> pygame.Rect:
        return pygame.Rect(0, 0, PANEL_W, self._wh)

    def _ctrl_rect(self) -> pygame.Rect:
        return pygame.Rect(8, 8, PANEL_W - 16, self._wh // 2 - 16)

    def _narr_rect(self) -> pygame.Rect:
        ctrl_h = self._wh // 2
        # Reserve a bottom strip for the Cogs/score line (drawn at wh-56).
        bottom = self._wh - 60
        return pygame.Rect(8, ctrl_h + 4, PANEL_W - 16,
                           bottom - (ctrl_h + 4))

    def _canvas_rect(self) -> pygame.Rect:
        return pygame.Rect(PANEL_W, 0, self._ww - PANEL_W, self._wh - 2)

    def _back_btn_rect(self) -> pygame.Rect:
        bw, bh = 60, 24
        return pygame.Rect(PANEL_W - bw - 8, self._wh - bh - 8, bw, bh)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._btn_rects: dict[str, pygame.Rect] = {}
        self._screen.fill(T.BG)

        # Panel background
        pygame.draw.rect(self._screen, T.PANEL, self._panel_rect())
        pygame.draw.line(self._screen, T.BORDER,
                         (PANEL_W, 0), (PANEL_W, self._wh), 1)

        self._draw_controls()
        self._draw_narrative()
        self._draw_canvas()
        self._draw_back_btn()
        self._draw_score()

        # Jump input overlay
        if getattr(self, "_show_jump_input", False):
            ow, oh = 260, 60
            ox = self._ww // 2 - ow // 2
            oy = self._wh // 2 - oh // 2
            jr = pygame.Rect(ox, oy, ow, oh)
            pygame.draw.rect(self._screen, T.PANEL_DEEP, jr, border_radius=6)
            pygame.draw.rect(self._screen, T.PHOSPHOR, jr, 1, border_radius=6)
            lt = self._fmd.render(
                f"Jump to challenge: {self._jump_input_str}_",
                True, T.WHITE_GREEN)
            self._screen.blit(lt, (ox + 10, oy + 18))
            ht = self._fsm.render("(Enter to confirm, Esc to cancel)",
                                   True, T.TEXT_DIM)
            self._screen.blit(ht, (ox + 10, oy + 40))

        if self._nav.is_active:
            self._nav.draw_overlay(self._screen,
                                   self._ww, self._wh,
                                   self._fhd, self._fsm,
                                   self._btn_rects)
        if self._nav.confirmed:
            pygame.quit()
            sys.exit(0)

        pygame.display.flip()

    def _draw_controls(self) -> None:
        cr = self._ctrl_rect()
        x, y = cr.x, cr.y
        w    = cr.width

        # Title
        tt = self._fhd.render("FIELD TRIP", True, T.WHITE_GREEN)
        self._screen.blit(tt, (x, y)); y += 28
        pygame.draw.line(self._screen, T.BORDER,
                         (x, y), (x + w, y), 1); y += 8

        state = self._state

        if state == "welcome":
            self._draw_btn("▶  Start", "btn_start", x, cr.bottom - 44, w, 36,
                           accent=self._dlg.is_done)

        elif state in ("tutorial_attractor", "tutorial_repulsor",
                       "challenge_build"):
            ch = self._current_challenge()
            # Challenge label
            lt = self._fsm.render(ch.label, True, T.AMBER)
            self._screen.blit(lt, (x, y)); y += 18

            # Objective summary — bullets derived from the challenge data.
            _MARK = {
                "reach":  ("\u2605", (255, 220, 0)),    # ★ gold
                "avoid":  ("\u2717", (220, 60, 60)),    # ✗ red
                "ignore": ("\u25cb", (130, 130, 150)),  # ○ grey
            }
            for marker, text in ch.requirements_summary():
                glyph, col = _MARK.get(marker, ("\u2022", T.TEXT_DIM))
                bt = self._fsm.render(f" {glyph} {text}", True, col)
                self._screen.blit(bt, (x, y)); y += 15
            y += 4

            # Robot summary
            n_sensors = len(self._robot_cfg.get("sensors", {}))
            n_motors  = len(self._robot_cfg.get("motors",  {}))
            rt = self._fsm.render(
                f"Sensors: {n_sensors}  Motors: {n_motors}", True, T.TEXT_DIM)
            self._screen.blit(rt, (x, y)); y += 16

            # Sensor policy summary
            for sid, pos in self._robot_cfg.get("sensors", {}).items():
                pol = pos.get("policy", "attract")
                col = (80, 160, 255) if pol == "attract" else (255, 80, 80)
                sign = "(+)" if pol == "attract" else "(−)"
                st = self._fsm.render(f"  {sign} {sid}", True, col)
                self._screen.blit(st, (x, y)); y += 14

            # Buttons
            btn_y = cr.bottom - 92
            self._draw_btn("Build Robot  →", "btn_open_builder",
                           x, btn_y, w, 34, accent=True)
            can_run = n_sensors > 0 and n_motors >= 2
            self._draw_btn("▶  Run", "btn_run",
                           x, btn_y + 42, w, 34,
                           accent=can_run, disabled=not can_run)

        elif state == "challenge_run":
            ch  = self._current_challenge()
            lt  = self._fsm.render(ch.label, True, T.AMBER)
            self._screen.blit(lt, (x, y)); y += 18

            # DEBUG (throwaway): show live tangential swirl set via [ ] \ keys
            _sw = getattr(self, "_dbg_swirl", 0.0)
            if _sw:
                dbg = self._fsm.render(
                    f"[debug] swirl={_sw:+.1f}  ([ ] adjust, \\ reset)",
                    True, T.TEXT_DIM)
                self._screen.blit(dbg, (x, y)); y += 16

            if self._sim:
                # Timer bar
                dur    = ch.duration_s
                remain = max(0.0, dur - self._sim.elapsed)
                frac   = remain / dur
                bar_w  = w - 4
                bar_h  = 12
                by     = y + 4
                pygame.draw.rect(self._screen, T.PANEL_DEEP,
                                 (x, by, bar_w, bar_h), border_radius=3)
                pygame.draw.rect(self._screen, T.PHOSPHOR,
                                 (x, by, int(bar_w * frac), bar_h),
                                 border_radius=3)
                tr = self._fsm.render(f"{remain:.1f}s", True, T.TEXT_DIM)
                self._screen.blit(tr, (x, by + bar_h + 2))
                y = by + bar_h + 18

                # IR fold-back is invisible in the sim otherwise — say so.
                import engine.sensor_physics as _sp
                if _sp.IR_FOLDBACK:
                    fb = self._fsm.render("IR FOLD-BACK ON", True, T.AMBER)
                    self._screen.blit(fb, (x, y)); y += 16

            # Force debug display
            if self._sim and self._sim.sensors:
                fy_ref = cr.bottom - 160
                for s in self._sim.sensors:
                    from engine.field_trip.field_physics import (
                        compute_sensor_reading, ATTRACT)
                    total_r = 0.0
                    for src2 in self._sim.challenge.sources:
                        r = compute_sensor_reading(
                            s, self._sim.robot.x, self._sim.robot.y,
                            self._sim.robot.heading, src2,
                            self._sim.challenge.arena)
                        total_r += r
                    pol = "+" if s.policy == ATTRACT else "-"
                    col = (80,160,255) if s.policy == ATTRACT \
                          else (255,80,80)
                    dl = self._fsm.render(
                        f"{s.sensor_id}({pol}) sig={total_r:.3f}",
                        True, col)
                    self._screen.blit(dl, (x, fy_ref)); fy_ref += 14
                # Net force
                from engine.field_trip.field_physics import compute_force
                fx2, fy2 = compute_force(
                    self._sim.sensors, self._sim.challenge.sources,
                    self._sim.robot.x, self._sim.robot.y,
                    self._sim.robot.heading,
                    self._sim.challenge.arena)
                fl = self._fsm.render(
                    f"F=({fx2:.3f},{fy2:.3f})", True, T.TEXT_DIM)
                self._screen.blit(fl, (x, fy_ref))

            self._draw_btn("■  Stop", "btn_stop",
                           x, cr.bottom - 44, w, 36, accent=False)

        elif state == "challenge_result":
            self._draw_result_controls(x, y, w, cr)

        elif state == "tutorial_complete":
            self._draw_btn("Begin Challenges  →", "btn_next",
                           x, cr.bottom - 44, w, 36,
                           accent=self._dlg.is_done)

        elif state == "challenge_done":
            dt2 = self._fmd.render("All challenges complete!", True, T.AMBER)
            self._screen.blit(dt2, (x, y))

    def _draw_result_controls(self, x, y, w, cr) -> None:
        ch   = self._current_challenge()
        won  = self._sim and self._sim.success
        cogs = self._last_cogs

        # Result header
        if won:
            col = T.PHOSPHOR
            msg = f"Success! — {self._score.cog_label(cogs)} Cog"
            if cogs == 3:
                msg += " ★★★"
            elif cogs == 2:
                msg += " ★★"
            else:
                msg += " ★"
        else:
            col = (220, 60, 60)
            msg = self._sim.fail_reason if self._sim else "Failed"

        rt = self._fmd.render(msg, True, col)
        self._screen.blit(rt, (x, y)); y += 22

        # Cog icons (simple colored circles)
        if won:
            cog_col = self._score.cog_color(cogs)
            cx_ = x + 8
            for i in range(3):
                filled = i < cogs
                pygame.draw.circle(self._screen, cog_col if filled else T.BORDER,
                                   (cx_ + i * 22, y + 8), 8,
                                   0 if filled else 2)
            y += 24

        # Attempts used
        at = self._fsm.render(
            f"Attempts: {self._attempts}", True, T.TEXT_DIM)
        self._screen.blit(at, (x, y)); y += 16

        # Buttons
        btn_y = cr.bottom - 136
        if won:
            self._draw_btn("Next  →", "btn_next",
                           x, btn_y, w, 34, accent=True)
            btn_y += 42
        elif self._current_challenge().teaching_wall and self._attempts >= 1:
            # Teaching-wall release valve: this challenge is deliberately
            # unsolvable with the current controls, so let the player move on
            # after a genuine attempt instead of being hard-stuck.
            self._draw_btn("Move on  →", "btn_next",
                           x, btn_y, w, 34, accent=True)
            btn_y += 42

        self._draw_btn("Retry", "btn_retry",
                       x, btn_y, w, 34)
        btn_y += 42

        if not self._nudge_shown and self._attempts >= 3 and not won:
            self._draw_btn("Hint", "btn_nudge",
                           x, btn_y, w, 28, accent=False)
            btn_y += 36

        if (self._nudge_shown and not self._solution_shown and not won
                and not self._current_challenge().teaching_wall):
            self._draw_btn("Show Solution", "btn_solution",
                           x, btn_y, w, 28, accent=False)

    def _draw_narrative(self) -> None:
        nr = self._narr_rect()
        if self._show_dlg and self._dlg:
            # Size the dialogue box to fill the narration rect (matching how
            # Ethology/VV size theirs to their layout rect), so the box border
            # hugs the region instead of the old fixed wh//3 with dead space.
            inner = nr.inflate(-8, -8)
            self._dlg._w = inner.width
            self._dlg._h = inner.height
            self._dlg.draw(self._screen, inner.x, inner.y)
        else:
            pygame.draw.rect(self._screen, T.PANEL_DEEP, nr, border_radius=4)
            pygame.draw.rect(self._screen, T.BORDER, nr, 1, border_radius=4)


    def _arena_rect(self, ch) -> "pygame.Rect":
        """Aspect-preserving canvas rect. Now shared — see engine.arena.arena_rect.

        This used to be Field Trip's private implementation, and its absence
        elsewhere was why RE and VV arenas ran to the window edge.
        """
        from engine.arena import arena_rect as _arena_rect
        return _arena_rect(self._canvas_rect(), ch.arena)

    def _draw_canvas(self) -> None:
        cr = self._canvas_rect()
        pygame.draw.rect(self._screen, T.BG, cr)
        # During the C0 intro, the canvas has no challenge yet. Rather than leave
        # it blank (which looks frozen), show a clear continue cue once the intro
        # narration has finished.
        if self._state == "tutorial_intro":
            if self._show_dlg and self._dlg and self._dlg.is_done:
                msg = self._fmd.render("Click anywhere to begin \u25b6",
                                       True, T.WHITE_GREEN)
                self._screen.blit(
                    msg, (cr.centerx - msg.get_width() // 2,
                          cr.centery - msg.get_height() // 2))
            else:
                msg = self._fsm.render("(read on, then click to continue)",
                                       True, T.TEXT_DIM)
                self._screen.blit(
                    msg, (cr.centerx - msg.get_width() // 2,
                          cr.centery - msg.get_height() // 2))
            return
        # Override cr with aspect-ratio-correct rect
        ch_tmp = None
        if self._state not in ("welcome", "tutorial_intro",
                               "tutorial_complete", "challenge_done"):
            ch_tmp = self._current_challenge()
            cr = self._arena_rect(ch_tmp)

        ch = ch_tmp
        if ch is None:
            return

        # Draw arena preview / simulation
        if self._state == "challenge_run" and self._sim:
            draw_arena(self._screen, cr, ch.arena,
                       robot_states=[self._sim.robot],
                       traces={"robot": self._sim.trace},
                       font_sm=self._fsm)
        elif self._state in ("challenge_build", "tutorial_attractor",
                             "tutorial_repulsor"):
            # The arena is shown while building so the player can see what they
            # are wiring for. It carries no label: the panel is obviously not
            # interactive, and naming it "read only" drew attention to a
            # limitation rather than to the arena.
            draw_arena(self._screen, cr, ch.arena,
                       font_sm=self._fsm)
        elif self._state == "challenge_result" and self._sim:
            draw_arena(self._screen, cr, ch.arena,
                       robot_states=[self._sim.robot],
                       traces={"robot": self._sim.trace},
                       font_sm=self._fsm)
        else:
            draw_arena(self._screen, cr, ch.arena,
                       font_sm=self._fsm)

        # Overlay: mark required targets and repulsors
        self._draw_source_overlays(cr, ch)

    def _draw_source_overlays(self, cr: pygame.Rect,
                               ch: Challenge) -> None:
        """Draw ★ on required targets, ✕ on required repulsors."""
        arena = ch.arena
        scl   = arena_scale(cr, arena)

        def w2s(wx, wy):
            return world_to_screen(wx, wy, cr, arena)

        for sid in ch.required_reach:
            src = ch.source_by_id(sid)
            if src and src.stype == "light":
                sx, sy = w2s(src.x, src.y)
                lbl = self._fsm.render("★", True, (255, 220, 0))
                self._screen.blit(lbl, (sx - lbl.get_width()//2,
                                        sy - lbl.get_height()//2))

        for sid in ch.required_avoid:
            src = ch.source_by_id(sid)
            if src:
                if src.stype == "light":
                    sx, sy = w2s(src.x, src.y)
                else:
                    sx, sy = w2s(src.x, src.y)
                lbl = self._fsm.render("✕", True, (220, 60, 60))
                self._screen.blit(lbl, (sx - lbl.get_width()//2,
                                        sy - lbl.get_height()//2))

    def _draw_score(self) -> None:
        """Score display — bottom-right of panel."""
        x = 8
        y = self._wh - 56
        tot = self._fsm.render(
            f"Cogs: {self._score.total}  ★ ×{self._score.streak}",
            True, T.TEXT_DIM)
        self._screen.blit(tot, (x, y))

    def _draw_back_btn(self) -> None:
        r    = self._back_btn_rect()
        mx, my = pygame.mouse.get_pos()
        hov  = r.collidepoint(mx, my)
        pygame.draw.rect(self._screen, T.PANEL_DEEP, r, border_radius=3)
        pygame.draw.rect(self._screen, T.PHOSPHOR_MID if hov else T.BORDER,
                         r, 1, border_radius=3)
        lbl = self._fsm.render("Back", True,
                               T.WHITE_GREEN if hov else T.TEXT_DIM)
        self._screen.blit(lbl, (r.centerx - lbl.get_width()//2,
                                r.centery - lbl.get_height()//2))

    def _draw_btn(self, label: str, name: str,
                  x: int, y: int, w: int, h: int,
                  accent: bool = False,
                  disabled: bool = False) -> pygame.Rect:
        r    = pygame.Rect(x, y, w, h)
        mx, my = pygame.mouse.get_pos()
        hov  = r.collidepoint(mx, my) and not disabled

        if disabled:
            fill   = T.PANEL_DEEP
            border = T.BORDER_DIM if hasattr(T, "BORDER_DIM") else T.BORDER
            tc     = T.TEXT_DIM
        elif accent:
            fill   = T.PANEL_DEEP
            border = T.PHOSPHOR if hov else T.PHOSPHOR_MID
            tc     = T.WHITE_GREEN
        else:
            fill   = T.PANEL_DEEP
            border = T.BORDER
            tc     = T.TEXT_DIM if not hov else T.TEXT

        pygame.draw.rect(self._screen, fill,   r, border_radius=4)
        pygame.draw.rect(self._screen, border, r, 1, border_radius=4)
        lt = self._fsm.render(label, True, tc)
        self._screen.blit(lt, (r.centerx - lt.get_width()//2,
                               r.centery - lt.get_height()//2))
        if not disabled:
            self._btn_rects[name] = r
        return r


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Field Trip")
    ap.add_argument("--challenge", type=int, default=None,
                    help="Start at challenge number (1-based)")
    ap.add_argument("--ir-foldback", action="store_true",
                    help="Model the GP2Y0A21's close-range fold-back: below "
                         "~10 cm the sensor reports a DISTANT surface instead "
                         "of saturating. Weakens near-wall repulsion, which "
                         "makes wall-hugging possible. Off by default.")
    args = ap.parse_args()

    if args.ir_foldback:
        from engine.sensor_physics import set_ir_foldback
        set_ir_foldback(True)
        print("[IR] fold-back ON — sub-10cm readings fold back "
              "(contact reads like ~50 cm)")

    hub = Hub()
    if args.challenge is not None:
        idx = args.challenge - 1
        hub._challenge_idx = max(0, idx)
        hub._tut_phase     = 2   # skip tutorial
        hub._state         = "challenge_build"
    hub.run()

if __name__ == "__main__":
    main()
