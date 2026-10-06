"""
engine/field_trip/challenges.py
---------------------------------
Hand-authored challenge definitions for Field Trip, stages 1-3.
Stage 4+ uses procedural generation based on these design principles.

Challenge structure:
    arena          : dict (standard arena format)
    sources        : list[FieldSource]
    required_reach : list[str]  — source_ids robot must reach
    required_avoid : list[str]  — source_ids robot must avoid
    neutral        : list[str]  — source_ids with no requirement
    stage          : int
    label          : str
    hint           : str        — shown after 3 failed attempts
    solution_desc  : str        — shown if player requests solution

Robot start position and heading come from arena["robot_start"].
"""

from __future__ import annotations
import math
import copy
from dataclasses import dataclass, field as dc_field
from engine.field_trip.field_physics import FieldSource

# ── World scale ───────────────────────────────────────────────────────────────
#
# Field Trip was authored around a 47 mm collision radius in a 0.6 x 0.8 m arena.
# That radius was never right: the chassis is DRAWN as a 169 mm octagon
# (robot_builder's bsquare_m), so the robot has always collided as a circle
# barely half the size of the body on screen, and slid through gaps its body
# could not fit.
#
# Robot Ethology carries the correct figure — games/ethology/robot.json gives
# body_radius 0.0775 — and its 1.5 x 2.5 m arena is sized for that robot. Since
# RE robots are analogues of the physical Field Trip robots, the two games
# disagreeing about how big a robot is was the anomaly.
#
# So: the collision radius is corrected to 0.0775, and every legacy arena is
# scaled by the same factor so relative layouts (corridor widths as a multiple
# of the body, light distances as a fraction of the arena) survive intact.
# 0.6 x 0.8 becomes 0.99 x 1.32 — comfortably inside RE's floor, which leaves
# room for maze challenges to use the whole of it later.
#
# NOT scaled, because they are physical facts about the board rather than
# properties of the layout:
#   - sensor mount offsets (a peg hole is where it is)
#   - the IR/LDR response curves (a sensor's 10 cm is 10 cm)
# The sensor curves not scaling is the whole point: a bigger arena with the same
# sensors is a genuinely different problem, not the same one drawn larger.

BODY_RADIUS_LEGACY = 0.047      # what Field Trip used to assume
BODY_RADIUS        = 0.0775     # games/ethology/robot.json — the real figure

# Legacy arenas are 0.6 x 0.8 as authored. They are now fitted to the shared
# canvas in engine/arena/world.py (1.5 x 2.5, the physical lab floor), which is
# a uniform x2.5 — content becomes 1.5 x 2.0 and is centred, leaving 25 cm of
# margin top and bottom rather than being stretched to fill.
#
# Six of the nine corridor-bearing challenges cross the ~30 cm sensor-honest
# floor as a result (c16, cp1..cp5): their walls move OUT of the IR's fold-back
# zone, where readings had been reporting a distant surface while touching a
# near one. c17/c18 still do not clear it (16.8 -> 25.4 cm) and remain a known
# exception.
from engine.arena.world import fit_to_canvas as _fit_to_canvas
WORLD_SCALE = min(1.5 / 0.6, 2.5 / 0.8)                    # 2.5

# Distance grows by WORLD_SCALE; the hub's motor speed rises from 0.25 to the
# 0.35 m/s hardware maximum (engine/robot/robot_model.py), so elapsed time grows
# by only WORLD_SCALE * 0.25/0.35. Legacy durations are stretched to match, which
# keeps every challenge's time budget the same in travel-distance terms.
DURATION_SCALE     = WORLD_SCALE * 0.25 / 0.35             # 1.7857...
# NOTE: this is a placeholder. Distances grew x2.5 while MOTOR_SPEED is already
# at the 0.35 m/s hardware ceiling, so budgets stretch to ~80 s. The intended
# fix is DELIBERATE ROBOT PLACEMENT — a bigger arena does not require starting
# the robot in the far corner — not a larger duration multiplier. Starts are
# carried through unchanged for now, pending review.


def load_arena_json(path: str) -> dict:
    """Load an arena from JSON, for challenges authored outside this file.

    The format is byte-identical to the dicts below and to the JSON that
    Robot Ethology loads and tools/arena_builder.py writes — same keys, same
    wall and light shapes. So an arena is portable across games, and a
    challenge cannot tell whether its arena was hand-authored or generated.

    Arenas loaded this way are ALREADY at the correct robot scale (they are
    authored against BODY_RADIUS, not the legacy 47 mm), so challenges using
    them must set prescaled=True.
    """
    import json as _json
    import os as _os
    if not _os.path.isabs(path):
        path = _os.path.join(_os.path.dirname(__file__), "..", "..", path)
    with open(_os.path.normpath(path)) as f:
        a = _json.load(f)
    a.setdefault("internal_walls", [])
    a.setdefault("light_sources", [])
    return a


def _scale_arena(arena: dict, k: float) -> dict:
    """Scale an arena's geometry by k. Pure similarity on the layout."""
    a = copy.deepcopy(arena)
    for key in ("width", "height", "wall_thickness"):
        if key in a:
            a[key] = a[key] * k
    for ls in a.get("light_sources", []):
        ls["x"] *= k
        ls["y"] *= k
        if "radius" in ls:
            ls["radius"] *= k
    for iw in a.get("internal_walls", []):
        for key in ("x0", "y0", "x1", "y1"):
            iw[key] *= k
        if "thickness" in iw:
            iw["thickness"] *= k
    rs = a.get("robot_start")
    if rs:
        rs["x"] *= k
        rs["y"] *= k          # heading is an angle — untouched
    return a


def _scale_sources(sources: list, k: float) -> list:
    out = []
    for s in sources:
        t = copy.deepcopy(s)
        for key in ("x", "y", "x0", "y0", "x1", "y1"):
            setattr(t, key, getattr(t, key) * k)
        t.radius = t.radius * k
        out.append(t)
    return out


def _scale_dwell(dz: dict | None, k: float) -> dict | None:
    """Dwell zones carry distances (and sometimes a position). Times do not."""
    if not dz:
        return dz
    d = copy.deepcopy(dz)
    for key in ("inner", "outer"):
        if key in d:
            d[key] = d[key] * k
    if "pos" in d:
        d["pos"] = tuple(v * k for v in d["pos"])
    return d

# ── Arena templates ───────────────────────────────────────────────────────────

def _arena(w=0.6, h=0.8, robot_x=0.0, robot_y=-0.30, heading=90.0,
           lights=None, walls=None):
    return {
        "width":          w,
        "height":         h,
        "wall_thickness": 0.025,
        "light_sources":  lights or [],
        "internal_walls": walls or [],
        "robot_start":    {"x": robot_x, "y": robot_y,
                           "heading_deg": heading},
    }

def _light(sid, x, y, color="white", radius=0.20, intensity=1.0):
    return FieldSource(source_id=sid, stype="light",
                       x=x, y=y, color=color,
                       radius=radius, intensity=intensity)

def _wall(sid, x0, y0, x1, y1):
    cx = (x0+x1)/2; cy = (y0+y1)/2
    return FieldSource(source_id=sid, stype="wall",
                       x=cx, y=cy, x0=x0, y0=y0, x1=x1, y1=y1)

def _arena_light(x, y, color="white", radius=0.20, intensity=1.0, sid=None):
    d = {"x": x, "y": y, "color": color,
         "radius": radius, "intensity": intensity}
    if sid:
        d["sid"] = sid
    return d

def _arena_wall(x0, y0, x1, y1, thickness=0.025, sid=None):
    d = {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
         "thickness": thickness}
    if sid:
        d["sid"] = sid
    return d


def _sources_from_arena(arena: dict) -> list:
    """Derive the FieldSource list from the arena geometry — the SINGLE SOURCE OF
    TRUTH. Each light/wall in the arena carries its own 'sid'; the matching
    FieldSource is built from the same numbers, so the two can never drift out of
    sync. Lights get ids light_0, light_1, ... (or their explicit sid); walls get
    wall_0, wall_1, ... (or their explicit sid)."""
    out = []
    for i, ls in enumerate(arena.get("light_sources", [])):
        sid = ls.get("sid", f"light_{i}")
        out.append(FieldSource(source_id=sid, stype="light",
                               x=ls["x"], y=ls["y"],
                               color=ls.get("color", "white"),
                               radius=ls.get("radius", 0.20),
                               intensity=ls.get("intensity", 1.0)))
    for i, iw in enumerate(arena.get("internal_walls", [])):
        sid = iw.get("sid", f"wall_{i}")
        cx = (iw["x0"] + iw["x1"]) / 2
        cy = (iw["y0"] + iw["y1"]) / 2
        out.append(FieldSource(source_id=sid, stype="wall",
                               x=cx, y=cy,
                               x0=iw["x0"], y0=iw["y0"],
                               x1=iw["x1"], y1=iw["y1"]))
    return out


# ── Challenge dataclass ───────────────────────────────────────────────────────

@dataclass
class Challenge:
    id:             str
    label:          str
    stage:          int
    arena:          dict
    # sources may be omitted — if empty, they are auto-derived from the arena
    # geometry (single source of truth). Provide explicitly only to override.
    sources:        list[FieldSource] = dc_field(default_factory=list)
    required_reach: list[str]      = dc_field(default_factory=list)
    required_avoid: list[str]      = dc_field(default_factory=list)
    neutral:        list[str]      = dc_field(default_factory=list)
    duration_s:     float          = 30.0
    hint:           str            = ""
    solution_desc:  str            = ""
    solution_file:  str            = ""  # filename in solutions/ folder
    # Region-dwell win: keep distance-to-target within [inner, outer] of the
    # named source continuously for hold_s. None = not a dwell challenge.
    # Annulus (inner>0, outer<big) = Orbit; stay-out (inner>0, outer huge) =
    # Flee/keep-away; stay-in (inner=0) = reach-and-remain. A dict:
    #   {"target": source_id, "inner": m, "outer": m, "hold_s": s}
    dwell_zone:     dict | None     = None
    # Tutorial narration. Slot dict keyed by moment: 'intro', 'build_hint',
    # 'on_run', 'success', 'retry'. Terms are marked 'Word(n)' and render in
    # the theme accent colour; 'glossary' is a list of (n, term, definition).
    # None = a normal (non-tutorial) challenge with no scripted narration.
    narration:      dict | None     = None
    # Teaching-wall challenge: DELIBERATELY unsolvable with the currently-available
    # control vocabulary (e.g. a Flow-around task while only Push/Pull is exposed).
    # The point is pedagogical — the player tries, discovers the limit, and PAW-BOT
    # names why. The result screen offers a "Move on" release valve so the player is
    # never hard-stuck. Set True to mark such a challenge.
    teaching_wall:  bool            = False
    # Legacy challenges were authored against BODY_RADIUS_LEGACY and are scaled
    # up by WORLD_SCALE on construction. Challenges authored natively at the
    # correct scale — anything loaded from arena JSON, and the maze
    # challenges — set this True to be left alone.
    prescaled:      bool            = False

    def __post_init__(self):
        # Bring legacy geometry up to the corrected robot scale before anything
        # else looks at it, so source derivation and validation both see the
        # same, already-scaled numbers.
        if not self.prescaled:
            # Layout scales; the boundary becomes the shared canvas.
            self.arena, k   = _fit_to_canvas(self.arena)
            self.dwell_zone = _scale_dwell(self.dwell_zone, k)
            if self.sources:
                self.sources = _scale_sources(self.sources, k)
            self.duration_s = self.duration_s * k * 0.25 / 0.35
            self.prescaled  = True

        # SINGLE SOURCE OF TRUTH enforcement. Lights/walls are written in TWO
        # places today — arena=... (geometry the game renders/collides) and
        # sources=... (what the sensors react to). They must describe the same
        # things. Here we either:
        #   (a) auto-derive sources from the arena when sources is omitted, or
        #   (b) VALIDATE that an explicit sources list matches the arena geometry,
        #       raising a clear error if they've drifted out of sync.
        derived = _sources_from_arena(self.arena)
        if not self.sources:
            self.sources = derived
            return
        # Validate: same set of light/wall GEOMETRY between arena and sources.
        def _geo(srcs):
            g = set()
            for s in srcs:
                if s.stype == "light":
                    g.add(("L", round(s.x, 4), round(s.y, 4)))
                elif s.stype == "wall":
                    g.add(("W", round(s.x0, 4), round(s.y0, 4),
                           round(s.x1, 4), round(s.y1, 4)))
            return g
        want, have = _geo(derived), _geo(self.sources)
        if want != have:
            missing = want - have          # in arena, not in sources
            extra   = have - want          # in sources, not in arena
            raise ValueError(
                f"Challenge {self.id}: arena and sources are OUT OF SYNC.\n"
                f"  In arena but not sources: {sorted(missing)}\n"
                f"  In sources but not arena: {sorted(extra)}\n"
                f"  Fix: make the arena=... and sources=... lists describe the "
                f"same lights/walls, or omit sources= to auto-derive from arena.")

    @property
    def has_attractor(self) -> bool:
        return bool(self.required_reach)

    @property
    def has_repulsor(self) -> bool:
        return bool(self.required_avoid)

    def source_by_id(self, sid: str) -> FieldSource | None:
        for s in self.sources:
            if s.source_id == sid:
                return s
        return None

    def _describe(self, sid: str, cryptic: bool) -> str:
        """Human description of a source for the requirements summary.

        For early stages (1-2) names are plain ("the green light"). For
        stage 3+ they are deliberately vaguer ("a light source", "an
        obstacle") so harder challenges keep some puzzle — the player must
        still work out WHICH source is which.
        """
        src = self.source_by_id(sid)
        if src is None:
            return sid
        if src.stype == "wall":
            return "a wall" if cryptic else "the wall"
        color = (src.color or "white").lower()
        if cryptic:
            return "a light source"
        if color in ("white", ""):
            return "the light"
        return f"the {color} light"

    def requirements_summary(self) -> list[tuple[str, str]]:
        """Objective as (marker, text) bullets, derived from the challenge
        data (required_reach / required_avoid / neutral). Stage 3+ uses
        vaguer source descriptions to preserve the puzzle.

        marker is one of: 'reach', 'avoid', 'ignore' — the caller styles each.
        """
        cryptic = self.stage >= 3
        out: list[tuple[str, str]] = []
        for sid in self.required_reach:
            out.append(("reach", f"Reach {self._describe(sid, cryptic)}"))
        for sid in self.required_avoid:
            out.append(("avoid", f"Avoid {self._describe(sid, cryptic)}"))
        for sid in self.neutral:
            # Neutral sources are the 'red herrings' — always worth naming as
            # present-but-ignorable, even when cryptic.
            out.append(("ignore",
                        f"Ignore {self._describe(sid, cryptic)} (a distraction)"))
        if not self.required_reach and self.required_avoid:
            out.append(("reach", "Survive the time limit without contact"))
        return out


# ── Stage 1: Single force ─────────────────────────────────────────────────────


# ── Stage 1: Single source, single flow style (tutorial C1-C4) ───────────────

# Shared glossary for the tutorial challenges. Terms are referenced in
# narration as "Word(n)" and render in the theme accent colour; this list
# supplies (number, term, definition) for the on-panel glossary.
_TUT_GLOSSARY = [
    (1, "virtual fields",
        "a physics-based metaphor for how environmental sources relate to a "
        "robot's motors through its sensors. Sources are treated as having "
        "magnetic- or gravity-like forces, pushing or pulling the robot in "
        "ways that help it navigate."),
    (2, "Seek",
        "the motion when a sensor tells the robot a source is \u201cpulling\u201d "
        "it, like a magnet to metal, or to a magnet of opposite polarity."),
    (3, "Flee",
        "the motion when a sensor tells the robot a source is \u201cpushing\u201d "
        "it away, like a magnet of the same polarity as the robot."),
    (4, "Orbit",
        "the motion when sensors pull the robot into a loop around a source. "
        "The orbit isn't a perfect circle and may drift inward or outward."),
    (5, "Flow-around",
        "the motion when the robot bends past a source like light bent around "
        "a massive object \u2014 or like a log riding a river current around "
        "a rock in its path."),
]

C1 = Challenge(
    id="c01", label="Follow the Light", stage=1,
    arena=_arena(
        lights=[_arena_light(0.0, 0.15)]),
    sources=[_light("light_0", 0.0, 0.15)],
    required_reach=["light_0"],
    hint="Place a forward-facing LDR sensor and set its flow style to Seek "
         "(toward). The robot drives toward the light.",
    solution_desc="One LDR·W sensor at the front, angle 0\u00b0, flow Seek.",
)

C2 = Challenge(
    id="c02", label="Avoid the Light", stage=1,
    duration_s=30.0,
    arena=_arena(
        lights=[_arena_light(0.0, 0.10)]),
    sources=[_light("light_0", 0.0, 0.10)],
    required_avoid=["light_0"],
    hint="Set your LDR sensor's flow style to Flee (away). "
         "The robot will be pushed away from the light.",
    solution_desc="One LDR·W sensor at the front, flow Flee. "
                  "The robot flees to the far end of the arena.",
)

C3 = Challenge(
    id="c03", label="Circle the Light", stage=1,
    arena=_arena(
        lights=[_arena_light(0.0, 0.15)]),
    sources=[_light("light_0", 0.0, 0.15)],
    required_reach=[],
    # Orbit dwell: hold the annulus around the light for 8s. Inner/outer band
    # matches the measured stable-orbit radius (≈0.20–0.31) with margin, so a
    # real (imperfect) orbit holds while Seek (collapses in) and Flee (escapes
    # out) both fail.
    dwell_zone={"target": "light_0", "inner": 0.13, "outer": 0.36,
                "hold_s": 8.0},
    duration_s=30.0,
    hint="Set a sensor to one of the two Orbit styles. Orbit pulls the robot "
         "into a loop around the light \u2014 not into it, not away from it.",
    solution_desc="One LDR·W sensor set to Orbit (either handedness). The "
                  "robot circles the light and holds the ring.",
)

C4 = Challenge(
    id="c04", label="Around the Obstacle", stage=1,
    duration_s=30.0,
    arena=_arena(
        lights=[_arena_light(0.0, 0.28)],
        walls=[_arena_wall(-0.06, 0.05, 0.30, 0.05)]),
    sources=[_light("light_0", 0.0, 0.28),
             _wall("wall_0", -0.06, 0.05, 0.30, 0.05)],
    required_reach=["light_0"],
    required_avoid=["wall_0"],
    hint="This one can't be beaten with Push and Pull alone. Push sends the "
         "robot straight away from the wall; Pull sends it straight toward the "
         "light. Neither can push it SIDEWAYS to round the wall \u2014 that "
         "sideways motion is a new idea you'll meet soon.",
    solution_desc="This challenge needs a sideways (circulation) force to round "
                  "the wall \u2014 a control style beyond Push and Pull. It is "
                  "here to show the edge of what Push/Pull can do.",
    solution_file="",
    teaching_wall=True,
)

C5 = Challenge(
    id="c05", label="Around and Guard", stage=2,
    arena=_arena(
        lights=[_arena_light(0.0, -0.05, color="red",
                             radius=0.30, intensity=1.2)],
        walls=[_arena_wall(-0.16, 0.20, 0.16, 0.20)]),
    sources=[_light("light_red", 0.0, -0.05, color="red",
                    radius=0.30, intensity=1.6),
             _wall("wall_0", -0.16, 0.20, 0.16, 0.20)],
    required_avoid=["light_red"],
    dwell_zone={"target": "wall_0", "inner": 0.0, "outer": 0.10,
                "hold_s": 4.0},
    duration_s=30.0,
    hint="The red light blocks the straight path to the wall. Go around it "
         "(Flow-around), then settle in close to the wall and hold your "
         "position there.",
    solution_desc="Flow-around the red light (LDR\u00b7R, either handedness) "
                  "+ Seek the wall (IR). The robot arcs around the light and "
                  "guards the wall.",
)


# ── Stage 2: Two sources ──────────────────────────────────────────────────────

C6 = Challenge(
    id="c06", label="Green vs Red", stage=2,
    arena=_arena(
        lights=[_arena_light(-0.12, 0.18, color="green"),
                _arena_light( 0.14, 0.24, color="red")]),
    sources=[_light("light_G", -0.12, 0.18, color="green"),
             _light("light_R",  0.14, 0.24, color="red")],
    required_reach=["light_G"],
    required_avoid=["light_R"],
    hint="Set an LDR·G sensor to Seek (toward) and an LDR·R sensor to Flee "
         "(away). Tip: if the robot goes straight, try angling your sensors "
         "so one side reads more strongly than the other.",
    solution_desc="LDR·G Seek angled left + LDR·R Flee angled right. "
                  "Asymmetric sensor angles create a net lateral force.",
    solution_file="FT_C06_solution.json",
)

C7 = Challenge(
    id="c07", label="Light and Wall", stage=2,
    arena=_arena(
        lights=[_arena_light(0.0, 0.25, color="green")],
        walls=[_arena_wall(0.08, -0.05, 0.08, 0.15)]),
    sources=[_light("light_G", 0.0, 0.25, color="green"),
             _wall("wall_0", 0.08, -0.05, 0.08, 0.15)],
    required_reach=["light_G"],
    required_avoid=["wall_0"],
    hint="The wall runs along your right side. An IR Repulsor keeps you "
         "clear of it — and if you set that sensor to flow AROUND the wall, "
         "the robot curves past instead of getting stuck against it.",
    solution_desc="LDR·G Seek for the light + a right-facing IR set to "
                  "Flow-around the wall. The robot rounds the wall and "
                  "continues to the light instead of stalling beside it.",
    solution_file="FT_C07_solution.json",
)

C8 = Challenge(
    id="c08", label="Wall Seeker", stage=2,
    arena=_arena(
        lights=[_arena_light(0.0, 0.10)],
        walls=[_arena_wall(-0.10, 0.25, 0.10, 0.25)]),
    sources=[_light("light_0", 0.0, 0.10),
             _wall("wall_0", -0.10, 0.25, 0.10, 0.25)],
    required_reach=["wall_0"],
    required_avoid=["light_0"],
    hint="You need to reach the wall at the far end while staying away from "
         "the light in the middle. Set an IR sensor to Seek (toward) and an "
         "LDR sensor to Flee (away).",
    solution_desc="IR Seek forward + LDR·W Flee. "
                  "The light pushes the robot aside as it homes in on the wall.",
)

C9 = Challenge(
    id="c09", label="Blue over Green", stage=2,
    arena=_arena(
        lights=[_arena_light(-0.05, 0.25, color="blue"),
                _arena_light( 0.05, 0.10, color="green")]),
    sources=[_light("light_B", -0.05, 0.25, color="blue"),
             _light("light_G",  0.05, 0.10, color="green")],
    required_reach=["light_B"],
    required_avoid=["light_G"],
    hint="Reach the blue light while avoiding green. Use colour-matched "
         "sensors: LDR·B set to Seek (toward) and LDR·G set to Flee (away).",
    solution_desc="LDR·B Seek + LDR·G Flee, both forward-facing. "
                  "The robot steers left past green toward blue.",
)

C10 = Challenge(
    id="c10", label="The Corridor", stage=2,
    arena=_arena(
        lights=[_arena_light(0.30, 0.28)],
        walls=[_arena_wall(-0.15, -0.20,  -0.15, 0.40),
               _arena_wall(0.15, -0.20,  0.15, 0.20)]),
    sources=[_light("light_0", 0.30, 0.28),
             _wall("wall_L", -0.15, -0.20,  -0.15, 0.40),
             _wall("wall_R", 0.15, -0.20,  0.15, 0.20)],
    required_reach=["light_0"],
    required_avoid=["wall_L", "wall_R"],
    hint="Two walls stagger across your path. A plain Repulsor pushes you "
         "straight back from a wall — and from the arena edges too — so it "
         "gets you stuck. Instead set one forward IR sensor to flow AROUND "
         "walls (repel + circulate): the robot curves past each wall toward "
         "the light.",
    solution_desc="LDR·W Seek (toward the light) + one forward IR set to "
                  "Flow-around (repel with circulation, ~2.5-3.0). The robot "
                  "rounds each staggered wall instead of being pushed back, "
                  "and reaches the light.",
    solution_file="FT_C10_solution.json",
)


# ── Stage 3: Neutral sources ──────────────────────────────────────────────────

C11 = Challenge(
    id="c11", label="Red Herring", stage=3,
    arena=_arena(
        lights=[_arena_light(-0.10, 0.15, color="red"),
                _arena_light( 0.10, 0.25, color="green")],
        walls=[_arena_wall(-0.15, 0.05, 0.15, 0.05)]),
    sources=[_light("light_R", -0.10, 0.15, color="red"),
             _light("light_G",  0.10, 0.25, color="green"),
             _wall("wall_0", -0.15, 0.05, 0.15, 0.05)],
    required_reach=["light_G"],
    required_avoid=["wall_0"],
    neutral=["light_R"],
    hint="The red light is a distraction. If you use a W-channel sensor, "
         "it will respond to red too — use a G-channel LDR set to Seek for "
         "the green light, and an IR set to Flow-around to get past the wall.",
    solution_desc="LDR·G Seek (green only) + IR Flow-around the wall. "
                  "Optionally add an LDR·R Flee to actively shun the red decoy.",
)

C12 = Challenge(
    id="c12", label="Blue Interference", stage=3,
    arena=_arena(
        lights=[_arena_light(0.0, 0.25, color="white"),
                _arena_light(0.0, 0.05, color="blue")],
        walls=[_arena_wall(-0.18, 0.15, 0.18, 0.15)]),
    sources=[_light("light_W", 0.0, 0.25, color="white"),
             _light("light_B", 0.0, 0.05, color="blue"),
             _wall("wall_0", -0.18, 0.15, 0.18, 0.15)],
    required_reach=["light_W"],
    required_avoid=["wall_0"],
    neutral=["light_B"],
    hint="The blue light sits between you and the target. "
         "A W-channel sensor will be drawn to both. Set white to Seek, blue "
         "to Flee to push through it, and an IR to Flow-around the wall.",
    solution_desc="LDR·W Seek + LDR·B Flee + IR set to Flow-around the wall.",
)

C13 = Challenge(
    id="c13", label="Choose Your Path", stage=3,
    arena=_arena(
        lights=[_arena_light(-0.15, 0.20, color="green"),
                _arena_light( 0.15, 0.20, color="red")],
        walls=[_arena_wall(0.0, -0.05, 0.0, 0.20)]),
    sources=[_light("light_G", -0.15, 0.20, color="green"),
             _light("light_R",  0.15, 0.20, color="red"),
             _wall("wall_0", 0.0, -0.05, 0.0, 0.20)],
    required_reach=["light_G"],
    required_avoid=["wall_0"],
    neutral=["light_R"],
    hint="A dividing wall splits the arena. Go left for green. "
         "Set an LDR·G sensor to Seek, and use an IR set to Flow-around so "
         "the robot rounds the divider instead of jamming against it.",
    solution_desc="LDR·G Seek + IR Flow-around the divider. "
                  "Robot rounds the wall toward green.",
)

C14 = Challenge(
    id="c14", label="Wall Magnet", stage=3,
    arena=_arena(
        lights=[_arena_light(0.0, 0.10, color="red")],
        walls=[_arena_wall(-0.10, 0.25, 0.10, 0.25),
               _arena_wall(-0.15, 0.05, 0.15, 0.05)]),
    sources=[_light("light_R", 0.0, 0.10, color="red"),
             _wall("wall_target", -0.10, 0.25, 0.10, 0.25),
             _wall("wall_block",  -0.15, 0.05, 0.15, 0.05)],
    required_reach=["wall_target"],
    required_avoid=["light_R", "wall_block"],
    neutral=[],
    hint="Set an IR sensor to Seek to reach the far wall, an LDR·R to Flee "
         "the red light, and a second IR to Flow-around the blocking wall in "
         "between so you don't stall against it.",
    solution_desc="IR Seek forward + LDR·R Flee + IR Flow-around the "
                  "blocking wall.",
)

C15 = Challenge(
    id="c15", label="The Gauntlet", stage=3,
    arena=_arena(
        lights=[_arena_light( 0.0,  0.30, color="green"),
                _arena_light(-0.15, 0.10, color="red"),
                _arena_light( 0.15, 0.10, color="blue")],
        walls=[_arena_wall(-0.08, 0.18, 0.08, 0.18)]),
    sources=[_light("light_G",  0.0,  0.30, color="green"),
             _light("light_R", -0.15, 0.10, color="red"),
             _light("light_B",  0.15, 0.10, color="blue"),
             _wall("wall_0", -0.08, 0.18, 0.08, 0.18)],
    required_reach=["light_G"],
    required_avoid=["light_R", "light_B", "wall_0"],
    neutral=[],
    hint="Three obstacles and a target. Set an LDR·G sensor to Seek the green "
         "light, LDR·R and LDR·B to Flee the red and blue, and an IR to "
         "Flow-around the wall. Balance them carefully.",
    solution_desc="LDR·G Seek + LDR·R Flee + LDR·B Flee "
                  "+ IR Flow-around the wall. Angles matter — experiment.",
)


# ── A mini maze: three lanes, gaps at alternating ends, forcing a serpentine ──
# Left inner wall hangs from the NORTH (y=+0.40) down to y=-0.20  -> gap at BOTTOM.
# Right inner wall rises from the SOUTH (y=-0.40) up to y=+0.20    -> gap at TOP.
# Robot starts NW corner facing DOWN; light sits in the lower-right corner.
# Forced path: DOWN the left lane, UNDER the left wall into the middle lane, UP the
# middle lane, OVER the right wall into the right lane, DOWN to the light. A full
# S-curve through all three lanes. Win: miss both walls, reach the light.
C16 = Challenge(
    id="c16", label="The Maze", stage=3,
    arena=_arena(
        robot_x=-0.25, robot_y=0.35, heading=270.0,
        lights=[_arena_light(0.0, -0.30, color="red",   radius=0.10, intensity=0.6),
                _arena_light(0.0,  0.30, color="green", radius=0.15, intensity=0.9),
                _arena_light(0.20, -0.30, color="blue", radius=0.22, intensity=1.4)],
        walls=[_arena_wall(-0.10, 0.40, -0.10, -0.20),
               _arena_wall( 0.10, -0.40,  0.10,  0.20)]),
    sources=[_light("light_R", 0.0, -0.30, color="red",   radius=0.10, intensity=0.6),
             _light("light_G", 0.0,  0.30, color="green", radius=0.15, intensity=0.9),
             _light("light_B", 0.20, -0.30, color="blue", radius=0.22, intensity=1.4),
             _wall("wall_L", -0.10, 0.40, -0.10, -0.20),
             _wall("wall_R",  0.10, -0.40,  0.10,  0.20)],
    required_reach=["light_B"],
    required_avoid=["wall_L", "wall_R"],
    duration_s=45.0,
    hint="Three coloured lights mark the way through the lanes: a dim RED just "
         "under the left wall, a GREEN up top, and the bright BLUE goal in the "
         "lower-right. Chase them in order with colour-matched LDRs (Seek R, then "
         "G, then B) \u2014 each pulls you toward the next gap. Use IR to keep off "
         "the walls.",
    solution_desc="Colour-matched seeks as breadcrumbs: LDR\u00b7R Seek -> LDR\u00b7G "
                  "Seek -> LDR\u00b7B Seek, each dimmer/nearer light handing off to "
                  "the next, plus IR flow-around the walls. The robot threads the "
                  "serpentine one waypoint at a time.",
    solution_file="",
)

# ── Spiral mazes: uniform-corridor square spiral. Walls only, NO lights first. ─
# A single coiling corridor from the CENTRE of the arena out to a CORNER. C17 runs
# centre->corner; C18 reuses the SAME walls corner->centre (start/goal swapped).
# No lights: the robot has only wall-repulsion + its base forward creep to navigate
# — a pure test of whether wall-following alone threads a spiral.
_SPIRAL_WALLS = [
    _arena_wall(-0.07, -0.07,  0.07, -0.07),   # inner bottom
    _arena_wall( 0.07,  0.07, -0.07,  0.07),   # inner top
    _arena_wall(-0.07,  0.07, -0.07, -0.07),   # inner left  (inner opens RIGHT)
    _arena_wall(-0.20, -0.20,  0.20, -0.20),   # outer bottom
    _arena_wall( 0.20, -0.20,  0.20,  0.20),   # outer right
    _arena_wall(-0.20,  0.20, -0.20, -0.20),   # outer left  (outer opens TOP)
    _arena_wall( 0.07, -0.07,  0.20, -0.07),   # corridor floor (forces the coil up)
]
_SPIRAL_WALL_SRCS = [
    _wall("sp0", -0.07, -0.07,  0.07, -0.07),
    _wall("sp1",  0.07,  0.07, -0.07,  0.07),
    _wall("sp2", -0.07,  0.07, -0.07, -0.07),
    _wall("sp3", -0.20, -0.20,  0.20, -0.20),
    _wall("sp4",  0.20, -0.20,  0.20,  0.20),
    _wall("sp5", -0.20,  0.20, -0.20, -0.20),
    _wall("sp6",  0.07, -0.07,  0.20, -0.07),
]

C17 = Challenge(
    id="c17", label="Spiral Out", stage=3,
    arena=_arena(robot_x=0.0, robot_y=0.0, heading=0.0,
                 lights=[], walls=list(_SPIRAL_WALLS)),
    sources=list(_SPIRAL_WALL_SRCS),
    required_reach=[],
    required_avoid=["sp0","sp1","sp2","sp3","sp4","sp5","sp6"],
    dwell_zone={"pos": (0.25, 0.35), "inner": 0.0, "outer": 0.07, "hold_s": 0.5},
    duration_s=60.0,
    hint="No lights this time \u2014 only walls. Start at the centre and wind "
         "your way out along the spiral corridor to the corner. Use IR to feel "
         "the walls and let them steer you around each turn.",
    solution_desc="Wall-following: IR repulsors keep the robot off the walls while "
                  "its forward creep carries it along the corridor, coiling out to "
                  "the corner.",
    solution_file="",
)

C18 = Challenge(
    id="c18", label="Spiral In", stage=3,
    arena=_arena(robot_x=0.25, robot_y=0.35, heading=225.0,
                 lights=[], walls=list(_SPIRAL_WALLS)),
    sources=list(_SPIRAL_WALL_SRCS),
    required_reach=[],
    required_avoid=["sp0","sp1","sp2","sp3","sp4","sp5","sp6"],
    dwell_zone={"pos": (0.0, 0.0), "inner": 0.0, "outer": 0.06, "hold_s": 0.5},
    duration_s=60.0,
    hint="Same spiral, reversed. Start at the corner and wind your way IN to the "
         "centre. Wall-following steers you around each turn toward the middle.",
    solution_desc="Wall-following inward: IR repulsors trace the corridor from the "
                  "corner down into the centre of the spiral.",
    solution_file="",
)

# ── PF BOUNDARY PROBES (dev12, rebuilt) — each arena's GEOMETRY AND START POSE are
# chosen so the robot MUST encounter the feature under test; a probe that can be
# solved by some other route tests nothing. All corridors are >= 0.16 m
# centreline-to-centreline (the robot needs > 0.119 m just to fit: body radius
# 0.047 + wall half-thickness 0.0125 per side).
_PB = dict(stage=3, duration_s=45.0)

# Symmetric barrier straight between robot and goal: pure seek cancels laterally.
CP1 = Challenge(id="cp1", label="Probe: Centered Barrier", arena=_arena(
        robot_x=0.0, robot_y=-0.30, heading=90.0,
        lights=[_arena_light(0.0, 0.30, intensity=1.4)],
        walls=[_arena_wall(-0.16, 0.05, 0.16, 0.05)]),
    required_reach=["light_0"], required_avoid=["wall_0"],
    hint="A symmetric barrier dead ahead — a straight Seek cancels and stalls. "
         "Break the symmetry with an asymmetric flow-around (IR flee + circulation).",
    solution_desc="Push/Pull only: LDR Seek angled -45 (left) plus an IR Flee aimed -90 (hard right). The asymmetry makes the resultant rotate as the robot turns — emergent circulation, no tangential needed.",
    solution_file="FT_CP1_solution.json",
    **_PB)

# Concave pocket whose MOUTH faces the robot, goal beyond its closed end: the
# classic local minimum. Pocket is 0.20 wide, start below the mouth.
CP2 = Challenge(id="cp2", label="Probe: U-Trap (concave)", arena=_arena(
        robot_x=0.0, robot_y=-0.32, heading=90.0,
        lights=[_arena_light(0.0, 0.34, intensity=1.4)],
        walls=[_arena_wall(-0.10, 0.18, -0.10, -0.10),
               _arena_wall( 0.10, 0.18,  0.10, -0.10),
               _arena_wall(-0.10, 0.18,  0.10,  0.18)]),
    required_reach=["light_0"], required_avoid=["wall_0","wall_1","wall_2"],
    hint="The goal lies straight beyond a concave pocket. Seek drives you in and "
         "pins you at the back wall — the classic local minimum. Circulation can "
         "slide you out sideways.",
    solution_desc="Push/Pull only: same asymmetric pair (LDR Seek -45, IR Flee -90, offset left). Emergent circulation slides the robot out of the pocket rather than pinning it.",
    solution_file="FT_CP2_solution.json",
    **_PB)

# TRUE double-back: the robot starts at the CLOSED TOP of a corridor with the goal
# up and to the right. The only exit is DOWNWARD, directly away from the goal, then
# around the outside — so the path must reverse in y.
CP3 = Challenge(id="cp3", label="Probe: Double-Back", arena=_arena(
        robot_x=0.0, robot_y=0.20, heading=90.0,
        lights=[_arena_light(0.24, 0.34, intensity=1.4)],
        walls=[_arena_wall(-0.09, -0.14, -0.09, 0.30),
               _arena_wall( 0.09, -0.14,  0.09, 0.30),
               _arena_wall(-0.09,  0.30,  0.09, 0.30)]),
    required_reach=["light_0"], required_avoid=["wall_0","wall_1","wall_2"],
    hint="You start boxed in near the top of a corridor; the light is up and to the "
         "right, but the corridor is capped above you. The only way out is DOWN and "
         "around the bottom — so reaching the light means first travelling away "
         "from it, the whole length of the corridor.",
    solution_desc="Push/Pull only, and only just — 2 of 729 configs solve. LDR Seek +45 offset right with IR Flee +20 offset right."
                  "exit runs sustainedly away from the goal, which needs memory.",
    solution_file="FT_CP3_solution.json",
    **_PB)

# Shallow spiral, goal OUTSIDE: corridors widened to 0.16. The light pulls the
# robot out through the opening, so this stays reachable (unlike a deep centre-goal
# spiral, which is not).
CP4 = Challenge(id="cp4", label="Probe: Shallow Spiral (out)", arena=_arena(
        robot_x=0.18, robot_y=-0.18, heading=180.0,
        lights=[_arena_light(0.0, 0.0, intensity=1.4)],
        walls=[_arena_wall(-0.10, -0.10,  0.10, -0.10),
               _arena_wall( 0.10,  0.10, -0.10,  0.10),
               _arena_wall(-0.10,  0.10, -0.10, -0.10),
               _arena_wall(-0.26, -0.26,  0.26, -0.26),
               _arena_wall( 0.26, -0.26,  0.26,  0.26),
               _arena_wall(-0.26,  0.26, -0.26, -0.26),
               _arena_wall( 0.10, -0.10,  0.26, -0.10)]),
    required_reach=["light_0"], required_avoid=[f"wall_{i}" for i in range(7)],
    hint="You start in the long outer arm of the coil, facing along it. Wind your "
         "way inward to the light at the centre.",
    solution_desc="Push/Pull only — the single solving config found: LDR Seek -70 offset right, IR Flee -70 centred."
                  "circulation follows the corridor inward.",
    solution_file="FT_CP4_solution.json",
    **_PB)

# Dead-end LURE: the robot starts OUTSIDE the pocket and the goal sits directly
# beyond its closed end, so the gradient pulls it in. Escaping means backing out
# (away from the goal) and taking the outside route.
CP5 = Challenge(id="cp5", label="Probe: Dead-End (needs memory)", arena=_arena(
        robot_x=0.0, robot_y=0.14, heading=270.0,
        lights=[_arena_light(0.0, 0.34, intensity=1.4)],
        walls=[_arena_wall(-0.09, -0.20, -0.09, 0.20),
               _arena_wall( 0.09, -0.20,  0.09, 0.20),
               _arena_wall(-0.09,  0.20,  0.09, 0.20)]),
    required_reach=["light_0"], required_avoid=["wall_0","wall_1","wall_2"],
    hint="You start deep inside a capped pocket, facing away from the light — the "
         "light is just beyond the cap above you. Getting there means backing all "
         "the way out of the pocket and around the outside.",
    solution_desc="Push/Pull only: LDR Seek -20 with IR Flee -20, both offset left."
                  "back out of the pocket and around is exactly what this probes.",
    solution_file="FT_CP5_solution.json",
    **_PB)

# ── All challenges in order ───────────────────────────────────────────────────

# ── Ported from Robot Ethology ────────────────────────────────────────────────
# Same arena JSON that RE's hierarchy traverses (arena_corridor_test.json).
# RE solved it with Escape_Front + Avoid_Object + Cruise_ARC — the arc supplying
# the handedness that a symmetric cruise lacks. The open question this challenge
# exists to answer: can push/pull do the same? PF has a handedness route (lateral
# sensor offset -> emergent circulation) but no obvious forward-drive term when
# the side walls cancel and the goal light is occluded.
CP6 = Challenge(
    id="cp6", label="Probe: Serpentine Corridor", stage=4,
    arena=load_arena_json("games/ethology/arenas/arena_corridor_test.json"),
    prescaled=True,          # authored at BODY_RADIUS, not the legacy 47 mm
    required_reach=["light_0"],   # auto-derived id from the arena JSON
    duration_s=90.0,         # ~7.4 m of corridor at 0.35 m/s, plus correction
    hint=("The walls push from both sides at once and cancel. The light is "
          "hidden until the last stretch. What makes you go FORWARD?"),
    solution_desc=("Open question. RE's hierarchy needs a cruise behaviour for "
                   "drive and an ARC for handedness; a push/pull robot has "
                   "neither unless its morphology supplies them."),
)

ALL_CHALLENGES: list[Challenge] = [
    # C3 "Circle the Light" is DEFERRED from the Push/Pull sequence: Orbit is a
    # TANGENTIAL (circulation) behavior, unreachable by any combination of pure
    # radial Push/Pull forces. It returns once the tangential control vocabulary is
    # hardware-validated and re-exposed in the builder. The C3 definition is kept
    # intact below for that time. (See field_physics: Push/Pull = radial only.)
    C1, C2, C4, C5,
    C6, C7, C8, C9, C10,
    C11, C12, C13, C14, C15,
    C16,
    C17, C18,
    # PF boundary probes (playtest):
    CP1, CP2, CP3, CP4, CP5,
    CP6,
]

# Tutorial uses C1 (attractor) and C2 (repulsor)
TUTORIAL_ATTRACTOR_IDX = 0
TUTORIAL_REPULSOR_IDX  = 1


# ── Stage 4: Procedural generator ────────────────────────────────────────────

import random as _random

def generate_challenge(number: int, rng: _random.Random | None = None) -> Challenge:
    """
    Generate a stage 4+ challenge (number >= 16).
    Difficulty increases with number; layout is randomised within constraints.
    """
    if rng is None:
        rng = _random.Random()

    # Difficulty parameters scale with challenge number
    n        = number - 15          # 1-based offset into stage 4
    n_req    = min(2, 1 + n // 5)  # required sources: 1 → 2
    n_avoid  = min(3, 1 + n // 3)  # repulsors: 1 → 3
    n_neutral= min(2, n // 8)      # neutral: 0 → 2
    use_color = n >= 5              # colour-specific sensors after a few rounds

    arena_w = 0.6
    arena_h = 0.8
    sources = []
    arena_lights = []
    arena_walls  = []

    # Place one required attractor (light)
    colors = ["white", "red", "green", "blue"]
    target_color = rng.choice(colors) if use_color else "white"
    tx = rng.uniform(-0.15, 0.15)
    ty = rng.uniform(0.10, 0.30)
    sources.append(_light("target", tx, ty, color=target_color))
    arena_lights.append(_arena_light(tx, ty, color=target_color))
    required_reach = ["target"]

    # Place repulsors
    required_avoid = []
    avoid_colors = [c for c in colors if c != target_color]
    for i in range(n_avoid):
        if rng.random() < 0.5:
            # Light repulsor
            rc = rng.choice(avoid_colors) if use_color else "white"
            rx = rng.uniform(-0.20, 0.20)
            ry = rng.uniform(-0.15, 0.20)
            sid = f"rep_{i}"
            sources.append(_light(sid, rx, ry, color=rc, radius=0.15))
            arena_lights.append(_arena_light(rx, ry, color=rc, radius=0.15))
            required_avoid.append(sid)
        else:
            # Wall repulsor
            angle = rng.uniform(0, math.pi)
            cx = rng.uniform(-0.15, 0.15)
            cy = rng.uniform(-0.05, 0.20)
            length = rng.uniform(0.12, 0.22)
            dx = math.cos(angle) * length / 2
            dy = math.sin(angle) * length / 2
            x0, y0 = cx - dx, cy - dy
            x1, y1 = cx + dx, cy + dy
            sid = f"rep_{i}"
            sources.append(_wall(sid, x0, y0, x1, y1))
            arena_walls.append(_arena_wall(x0, y0, x1, y1))
            required_avoid.append(sid)

    # Place neutral sources
    neutral = []
    for i in range(n_neutral):
        nc = rng.choice(colors)
        nx_ = rng.uniform(-0.20, 0.20)
        ny_ = rng.uniform(-0.10, 0.25)
        sid = f"neu_{i}"
        sources.append(_light(sid, nx_, ny_, color=nc, radius=0.15))
        arena_lights.append(_arena_light(nx_, ny_, color=nc, radius=0.15))
        neutral.append(sid)

    arena = _arena(w=arena_w, h=arena_h,
                   lights=arena_lights, walls=arena_walls)

    return Challenge(
        id      = f"c{number:02d}",
        label   = f"Challenge {number}",
        stage   = 4,
        arena   = arena,
        sources = sources,
        required_reach = required_reach,
        required_avoid = required_avoid,
        neutral        = neutral,
        duration_s     = 30.0,
        hint    = "Consider which sensor types and policies will help you "
                  "reach the target while avoiding the marked sources.",
        solution_desc  = "Multiple solutions exist. "
                         "Try LDR colour-matched attractors and repulsors.",
    )
