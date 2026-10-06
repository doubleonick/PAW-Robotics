# Field Trip — Status & Goals

*A concise snapshot of where Field Trip (FT) stands and where it's headed.*

---

## What Field Trip is

FT is the **virtual-field** game in the PAW collection. The player builds a
robot by placing sensors and assigning each a behaviour relative to environmental
sources (lights, walls). The robot then navigates by reacting to the implied
field. FT is distinct from Valentino's Vehicles (the Braitenberg/wiring game) and
Robot Ethology (the behaviour-hierarchy game) — its identity is the field.

Player vocabulary (the "flow styles"): **Seek** (toward), **Flee** (away),
**Orbit** (circle), **Flow-around** (route past). These are taught in the
tutorial and used throughout.

---

## Current state

### Tutorial — DONE and playtested well
C1–C4 are the non-optional narrated tutorial, each teaching one motion:
- **C1 Follow the Light** (Seek)
- **C2 Avoid the Light** (Flee)
- **C3 Circle the Light** (Orbit, dwell-based)
- **C4 Around the Obstacle** (Flow-around)

C0 is a standalone franchise intro (narration only, no arena) that names the four
motions and transitions into C1. The double-"Welcome" bug is fixed; the narration
rhythm reads well. **You confirmed C0–C4 play well.**

### Narration system — DONE
Author-editable, @slot-delimited script files (`games/field_trip/scripts/
field_trip/ft_c0.txt … ft_c4.txt`, `ft_glossary.txt`). Two markup notations,
both rendering correctly:
- `*term*(n)` — highlight only (amber + number, no footnote)
- `<term>(n)` — highlight **and** a bottom-anchored page footnote
Footnotes are pinned to the canvas bottom with a separator rule (manuscript
style). The DialogueBox also gained forward/back paging (benefits all games).

### Challenge arc C5+ — IN FLUX
C5 "Around and Guard" is committed and verified (geometry-forced Flow-around: a
red light blocks the straight path to a wall; the robot must arc around it and
dwell at the wall; lazy straight-Seek fails by clipping the light).

C6–C15 still hold older, partly-relabelled content and are **slated for
replacement** by a playful, logic-gate-themed arc (see Goals). The gate arc was
designed and partly verified but NOT yet committed as the live C5–C8.

### Builder UI — CLEANED
The flow-style picker is now Field-Trip-only (gated behind a `flow_styles` flag
on the shared `RobotBuilder`). It no longer leaks into Valentino's Vehicles.

### Engine — a foundational question is OPEN (see Goals)
A core force-model bug was found and fixed (colour-leak: a colour-matched sensor
was being pulled toward off-colour lights). Separately, a **foundational
divergence** was identified between the implemented model and the intended one —
this is the single biggest open question for FT.

---

## Goals (in priority order)

### 1. Resolve the force-model direction question (FOUNDATIONAL — open)
The current engine uses a **potential-field** model: force direction is the true
bearing from robot to source (the field "knows" where sources are); sensor
orientation only scales magnitude. The **intended** model is
**sensor-orientation-driven**: a dumb LDR reports only intensity; the field
DIRECTION comes from the sensor's mounting orientation in the robot frame, and
steering emerges from inter-sensor intensity differences as the robot turns,
filtered through differential drive.

These are different games: the current model lets a single sensor home; the
intended model needs multi-sensor designs and makes Orbit/Flow-around *emergent*
rather than explicit. A faithful rework would replace the core force formula and
re-tune/re-verify every challenge.

**Approach underway:** rather than rebuild the Python engine speculatively, the
intended model is being grounded the way Robot Ethology was — validated in
Arduino first (`PotentialFieldRobot` class, sensor-orientation + differential
drive, no swirl term), then translated to Python. Hardware testing pending. A
sandbox confirmed homing emerges; whether Orbit/Flow-around emerge from pure
pushes/pulls is the open empirical question (the world's field carries the
geometry; the robot only samples it — verification approach still being settled).

**Until this is decided, the force model is not being changed.**

### 2. Build the gate-themed C5–C8 arc, then swap C5+ wholesale
Playful, linguistically-themed challenges (rigorous truth-table versions are a
later, separate goal):
- **AND** "Come AND Stay a While" — reach + dwell a light. *Verified.*
- **OR** "Here, OR There?" — reach either of two diagonal lights, don't loiter
  the other. *Foundation verified (colour-pick works post-bugfix); win-tuning
  deferred to real implementation.*
- **NOR** "None Of The Above" — Stonehenge ring of wall pillars; flee all, hold
  the clear interior; biased start so inaction fails. *Verified (as walls —
  lights proved unworkable for avoidance).*
- **NAND** "Just Don't Visit Both Together" — wall + light; a resetting
  both-proximity countdown. *Not yet verified; needs new machinery.*

Plan: finish verifying OR + NAND, then delete old C5–C15 and add the new arc in
one decisive swap, then playtest. Challenges will be scripted via the @slot
template. C13-style capstone (guard a wall while near green / avoiding red)
remains the long-term target the precursors build toward.

Key physics lessons banked: **lights make poor avoidance obstacles** (tiny
fail-radius + grace period) — use **walls** for avoid challenges, lights for
seek/orbit. More wall challenges wanted generally.

### 3. Deferred engine/UX upgrades (documented in FUTURE_WORK.md)
- **FW-001** — shared Glossary/Resources system across all games (revisitable
  glossary; suite-level `glossary/{field_trip,valentinos,robot_ethology}/`).
- **FW-002** — graded colour channels (partial colour in mixed/overlap regions;
  currently binary, which under-reports but never violates).
- **FW-003** — directionless ambient light (the white ambient floor currently
  sits in the per-source force term to preserve orbit/flow tuning; faithful fix
  needs a re-tune). Note: **may be subsumed by Goal 1** if the force model is
  reworked.

### 4. Collection-wide (affects FT)
Rename "Curious Robotics" → "Perception Action World Robotics" across the suite
(string sweep, done deliberately as its own pass).

---

## Things only confirmable with a human at a running GUI
Narration rhythm/pacing, glyph legibility, seeking *feel*, and — most
importantly — whether the eventual sensor-orientation model produces satisfying
emergent Orbit/Flow-around behaviour. Headless tests verify solvability and
correctness, not feel.

---

## dev14 status update (2026-08-05)

### Physics and scale changed substantially

- **Arena is now 1.5 x 2.5 m**, the shared canvas defined in
  `engine/arena/world.py` and used by all three games. Legacy 0.6 x 0.8 layouts
  are fitted uniformly (x2.5) on construction, so content occupies 1.5 x 2.0
  centred, with 25 cm margins top and bottom.
- **Collision radius corrected 0.047 -> 0.0775.** The old figure was a bug: the
  chassis was drawn at 169 mm while colliding as a 94 mm circle.
- **Polygon physics.** FT moved off its hand-rolled `_blocked()` circle test onto
  `PyBulletAdapter`, so a robot now collides as the chassis it is drawn as. A
  rectangle catches a wall on its corner and torques itself square; a triangle
  pivots on its nose.
- **Turn rate roughly doubled.** `omega` had been computed with the body width
  (0.155) standing in for the wheelbase (0.080). Large and immediately visible.
- Time budgets stretched x1.79 with the canvas fit. **This is a placeholder** —
  the intended fix is deliberate robot placement, not a larger multiplier.

### Corridors moved into the sensors' honest range

Six of nine corridor-bearing challenges crossed the ~30 cm floor below which a
side-mounted GP2Y0A21 folds back and reports a distant surface while touching a
near one:

| | before | after |
|---|---|---|
| c16 The Maze | 27.9 cm | 43.8 cm |
| cp1 | 20.2 | 31.4 |
| cp3 / cp5 | 24.6 | 38.8 |
| c17 / c18 Spiral | 16.8 | 26.6 — **still below the floor** |

The spirals remain a known exception, and their "not traversable by reactive
control" verdict remains **unverified** — now for a third reason.

### New

- **`load_arena_json()`** — FT can load arena JSON, in the same format RE loads
  and `tools/arena_builder.py` writes. A challenge cannot tell whether its arena
  was authored or generated.
- **cp6 "Probe: Serpentine Corridor"** (sequence position 23) — the same arena
  Robot Ethology's hierarchy traverses, ported over. RE solves it with
  Escape_Front + Avoid_Object + Cruise_Arc; push/pull also solves it, from 6 of
  225 coarse configs, all with a laterally offset side-facing IR.
- **`--ir-foldback`** flag, with an amber HUD tag while active.
- The "Arena Preview (read only)" label is gone — it drew attention to a
  limitation rather than to the arena.

### Broken

- **Four of five solution prefabs fail** (cp2–cp5). "Show Solution" loads a build
  that does not solve. Regeneration pending final physics; criteria agreed with
  the user are legibility first, robustness as tiebreaker, speed only as a floor.
- Every recorded solve count predating dev14 is void. `tools/pf_sweep.py` is the
  only re-runnable source.
