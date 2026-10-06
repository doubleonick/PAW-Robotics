# PAW-Robotics Changelog

## v2.6 — 2026-08-05  (dev14)

Theme: bringing **Perception, Action and World** into register across all three
games. Most of this session's findings were geometry and units, not control.

### World — one shared arena canvas
- **New `engine/arena/world.py`** is the single definition of arena dimensions:
  `CANVAS_W/H = 1.5 x 2.5` (the physical lab floor), `WALL_THICKNESS = 0.05`,
  `GRID_M = 0.25`, plus `SENSOR_HONEST_MIN_CORRIDOR = 0.30` and
  `PROX_GRADIENT_MIN_CORRIDOR = 0.36` for validators and generators.
  `fit_to_canvas()` scales an arena's LAYOUT uniformly; `conforms()` audits.
- Was: four arena sizes and three wall thicknesses (RE 1.5x2.5/0.05,
  VV 1.2x1.6/0.025, FT 0.99x1.32/0.041, NTV 0.5x1.0). Now all 1.5 x 2.5 / 0.05.
- **Scaled**: wall endpoints, light positions and radii, robot start.
  **Not scaled**: wall thickness (a physical block), the robot (a chassis
  property), sensor response curves (10 cm is 10 cm anywhere).
- Field Trip's collision radius corrected 0.047 -> 0.0775. The old value was a
  bug, not a choice: the chassis was DRAWN at 169 mm while colliding as a 94 mm
  circle, so the robot slid through gaps it visibly could not fit.
- Six of nine corridor-bearing challenges crossed the ~30 cm sensor-honest floor
  as a result (c16, cp1-cp5), moving their walls out of the IR fold-back zone.
  c17/c18 remain below it (26.6 cm) — a known exception.
- Field Trip can now load arena JSON (`challenges.load_arena_json`). The format
  was already identical to RE's, so arenas are portable between games.

### Action — polygon physics in all three games
- **Root cause found**: `robot_builder.CHASSIS["octagon"]` was 0.1690 while
  `robots/ethology_v2.json` (CAD) gives `bounding_square_mm = 155`. The file's
  own header comment said 155. 9% too big, and 0.155/2 = 0.0775 exactly — RE's
  `body_radius` IS the octagon inradius. Corrected, with the triangle that
  derives from it.
- `RobotConfig` carries `chassis_spec`, derived from `geometry` +
  `bounding_square` when a robot.json describes itself the CAD way.
- `RobotModel.create_body()` builds a **convex hull** from the chassis outline
  instead of a cylinder. Falls back to a cylinder when no spec is given.
- **Field Trip** moved off its hand-rolled `_blocked()` circle test and inline
  integration onto `PyBulletAdapter`. **Valentino's** moved off
  `SimpleDriveAdapter`. Both now collide as the polygon they are drawn as.
- Measured: a triangle driven at a wall catches on its nose and pivots 30
  degrees; a rectangle driven in at 60 degrees torques itself square against the
  face and slides. A circle can produce neither.
- **Wheelbase bug fixed.** FT computed `omega` using `BODY_RADIUS*2` (0.155)
  where `robots/ethology_v2.json` gives 0.080 — Field Trip had been simulating a
  robot turning at roughly half the real rate. Now `WHEEL_BASE = 0.080`.

### Action — PyBulletAdapter made to work
- The adapter had **never been executed**: `reset_pose()` was passed a
  `physicsClientId` it does not accept; `RobotModel.apply_drive()` did not exist;
  `load_world()` built `ArenaModel` and `RobotModel` without calling `build()`
  or `create_body()`. All four fixed.
- **New `tools/test_pybullet_adapter.py`** — 11 assertions. Its absence is
  exactly why the adapter sat broken.
- `step(left, right, dt)` confirmed as a **primitive duration** (hold this
  command this long), mirroring firmware `driveProportional(l, r, seconds)`, not
  a physics timestep. Verified: doubling `dt` doubles distance.
- Throughput ~110x realtime.

### Perception — thresholds and units
- **`PROX_THRESHOLD` 33/35/15 -> 20 cm** across simulator, both firmware
  variants, the shared `materials/` copy and the BT mock. The simulator had
  never used the robot's actual threshold.
- `CogProximity::analyzeData` maps raw to **[60,18] CENTIMETRES** — the sensor's
  practical band. The firmware's own comment saying "[10,80]" is wrong; the code
  is right. Matching wrong comment in the Python HAL corrected.
- `getData()` **saturates at 18 cm**, so a robot centred in a corridor narrower
  than ~36 cm has both sensors pinned and no gradient. That, not the threshold,
  is why `arena_spiral.json` (19 cm corridors) produced pure oscillation.
- **IR fold-back modelled, opt-in** (`set_ir_foldback`, `--ir-foldback`). Below
  ~10 cm the GP2Y0A21 reports a DISTANT surface while touching a near one; both
  simulators had clamped to 1.0. Off by default and bit-identical to the previous
  curve when off.

### Tools
- **`tools/pf_sweep.py`** — the 729-config solvability sweep, previously an
  uncommitted heredoc that no recorded result could be reproduced from.
- **`tools/arena_check.py`** — reachability, connected components, and maximin
  corridor clearance. The clearance metric was missing and is what revealed the
  c17/c18 spiral confound.
- **`engine/maze/`** — the maze generator ported from the Amazing Kingdoms web
  game, PRNG bit-identical to the JS, so a seed produces the same maze in both.

### Fixed
- **Arena Editor: Open did not put the arena into play.** `_arena_path` was both
  "file being edited" and "the slot the game reads back", so opening an arena
  redirected the save target and left `_dirty = False` — Save, Launch and Done
  all failed differently. Now `_session_path` is tracked separately.
- **Valentino's robots were dimensionless points.** `SimpleDriveAdapter` had no
  `body_radius`; the robot centre stopped at the wall with its front half buried.
  (Then briefly over-corrected to the octagon's radius, making it float 3 cm
  clear — fixed properly via `chassis_collision_radius`, then superseded by
  polygon collision.)
- `load_arena()`'s missing-file early return bypassed the canvas fit.

### Known broken
- **Four of five Field Trip solution prefabs fail** (cp2-cp5). "Show Solution"
  loads a build that does not solve. Broken by the scale migration; regeneration
  is pending final physics.
- **Valentino's vehicle demo does not play.** Undiagnosed.
- **RE and VV arenas render with partially occluded walls.** Undiagnosed; FT
  renders correctly and should be the model.

### Deprecated / dead
- `engine/arena.py` is permanently SHADOWED by the `engine/arena/` package and
  has never been imported. Marked, not deleted.
- `games/valentinos/arena/arena.py` duplicates the engine renderer byte for byte.
- `SimpleDriveAdapter` now has no callers.

## v2.5 — 2026-06-10

### Field Trip — sensor force-model fix (colour attribution)
- Fixed a force-model bug where an LDR sensor's per-channel reading was computed
  over the WHOLE arena and then applied toward EACH light's bearing in turn —
  smearing one light's signal across every source's direction. Effect: a
  colour-matched sensor (e.g. green channel) with an off-colour light present
  (e.g. red) was pulled toward the off-colour light, so a green-seeker would
  drift toward a red light instead of reaching green. This would have broken
  every multi-coloured-light challenge (incl. the planned C13 capstone and the
  OR gate). Fix: `ldr_reading` gains an `only_source` parameter; the force model
  now attributes each light's signal to its own bearing. Colour channels filter
  correctly in space, not just magnitude.
- White-channel sensing now correctly reads BRIGHTER where lights overlap
  (per-light intensities sum).
- Two model divergences documented for later (FUTURE_WORK): FW-002 graded colour
  channels (binary colour match → partial colour in mixed regions); FW-003
  directionless ambient (the white ambient floor currently sits in the per-source
  force term to preserve orbit/flow tuning; faithful fix needs a re-tune).
- Verified: C1–C5 all still pass; colour-leak case fixed.

### Field Trip — new challenge C5 "Around and Guard"
- Geometry-forced Flow-around: a red light blocks the straight path to a wall;
  the robot must arc around it (Flow-around) and dwell at the wall. Verified:
  intended build wins, straight-Seek fails by clipping the light.

## v2.3 — 2026-06-08

### Regression recovery (Valentino's Vehicles) — see REGRESSION_LOG.md
- R-001/R-002: BYOV chassis change + recording playback now render the correct
  chassis (was: always default rectangle, due to a refactor path mismatch in
  `RobotState`'s file read). Fixed by passing `chassis_spec` in from memory.
- R-003: BYOV playback scrubber now seeks on click/drag (was: inert; input
  wiring was missing). Added HUD `scrub_hit`/`seek_at` + hub mouse routing.
- Cross-game sweep (VV, NTV, Ethology, Field Trip) for the two regression
  patterns found no other damaging instances; full detail in REGRESSION_LOG.md.
- F-001 (theme persistence / settings.json path) logged as OPEN — needs
  confirmation before changing, not yet fixed.

### Virtual-field reframing (Field Trip) — see prior entries
- `force_to_motors` turn-toward-resultant steering; per-sensor `tangential`
  (swirl) term in `compute_force`; source `intensity` honored in `ldr_reading`.
- C7 made solvable (Flow-around); C6 color-discrimination fixed.

### VV consistency cleanup — see VV_AUDIT.md
- Deleted pre-adapter scaffolding (`games/valentinos/{main,simulator}.py`).
- Default Cowardice vehicle fixed to live sensor names (was inert).
- Stale RL/RR/PL/PR naming corrected in comments/defaults; legacy names kept
  valid for older saves + tests.


## v2.1 — 2026-06-01

### Valentino's Vehicles (VV)

#### Intro Sequence
- Replaced redundant 3-screen text-only opening with direct entry to V1 narration
- Demo sequence (V1–V3b): sim starts at correct moment per vehicle
  - V1: sim starts when last description page is reached; Continue activates simultaneously
  - V2a–V3b: Continue activates on prediction page; clicking Continue starts sim and advances to reveal
- Behavioral label (e.g. "Cowardice") hidden until demo runs; only vehicle number shown initially
- Yes/No wiring tutorial offer: stacked vertically, both buttons active when dialogue done
- byov_intro shown only once (gated on progress flag)

#### Wiring Tutorial
- Redesigned as 3-phase flow: V1 → V2a → V3b
  - V1: LDR·C1→FL, LDR·C1→FR (blue)
  - V2a: LDR·C1→FL, LDR·C2→FR (blue, ipsilateral)
  - V3b: LDR·C1→I2, LDR·C2→I1 (blue), N1→FL, N2→FR (blue) — contralateral inhibitory
- V3b neuron biases (N1=1.0, N2=1.0) auto-injected after successful wiring check
- Wrong-answer feedback scripts updated with correct sensor names (LDR·C1, LDR·C2, I1, I2)
- Wiring preview replaced with accurate text connection list
- Tutorial arena updated: robot closer to and offset from light for visible behavior

#### Name That Vehicle (NTV)
- Vehicle demos removed from NTV intro (covered by VV intro)
- New intro: brief explainer + Start Game button
- 10 vehicle definitions: 5 LDR + 5 IR, all using zone-qualified sensor names
- Dual-column answer UI: LDR column (amber) + IR column (green), each with 5 behaviors + N/A
- Both columns must be set before Verify activates
- Round progression:
  - Rounds 1–10: single sensor, single source, all 10 vehicles shuffled (no repeats)
  - Rounds 11–20: single sensor, two sources of matching type
  - Rounds 21+: mixed sensors (LDR + IR compound), arena has both source types
- Demo timer: 10 seconds all rounds
- Replay button: appears between guesses and after round ends
- View Wiring: shows correct sensor names (LDR·C1, LDR·C2, IR·L, IR·R)
- Feedback: shows player's guess (not correct answer) on wrong guess
- Correct answer revealed in amber after all attempts exhausted
- Back button: bottom-right of narrative panel, returns to VV menu
- Arena generator: _place_compound ensures both sensors stimulated from tick 1
  (robot near boundary wall for IR, light on opposite side for LDR)
- V1 renamed: "Light Response" → "Target Avoidance"

### Robot Ethology (RE)
- Robot heading fixed: arena editor and simulation now use same orientation convention
- Arena snapshot saved alongside recordings; restored during playback
- Shadows added to RE main view (_draw_canvas)
- Playback uses recorded arena config, not current arena

### Sensor Names
- Zone-qualified sensor IDs (LDR·C1, LDR·C2, IR·L, IR·R) added to VALID_SOURCES
- Legacy names (RL, RR, PL, PR) preserved for backward compatibility

### Calibration
- Confirmed: calibration uses PAW-Calibration device (19b1xxxx UUIDs)
- RE uses PAW-Ethology device (19b2xxxx UUIDs) — separate sketches

### BLE (Robot Ethology) — KNOWN ISSUE
- RE BLE hierarchy upload (PAW-Ethology, ethology_ble_robot.ino) not yet confirmed working
- Fixes applied this version:
  - asyncio and threading moved to top-level imports in robot_bt_client.py
  - response=True (ArduinoBLE Write With Response)
  - Threaded event loop (_cmd uses background thread with new event loop)
  - Error now printed to terminal: [BLE] error: ...
- Requires bleak: py -3.12 -m pip install bleak
- Status: untested after asyncio import fix — needs hardware verification next session

### Engine
- render_shadows.py: universal shadow rendering across all arena views
- IR sensor range corrected: NEAR_M=0.10, FAR_M=0.80 (was 0.457m)
- PyBullet renderer: LightSource objects converted to dicts for shadow rendering


## PENDING FEATURES (future sessions)

### Field Trip — Dynamic Sources
- Moving light/wall sources during simulation (not in builder — during run)
- MotionRule on FieldSource: pattern (circle, linear, chase, flee, random_walk), speed, params
- Robot chases moving attractor or flees pursuing repulsor
- Pedagogically distinct: demonstrates reactive tracking under dynamic fields
- Arena preview should indicate motion (arrow/orbit path) before run starts
- Suggested for Stage 4+ challenges
- Effort: medium (~2-3 sessions)

### Robot Ethology — BLE
- RE BLE hierarchy upload not yet confirmed working
- Fixes applied: asyncio top-level import, response=True, threaded event loop
- Needs hardware test with PAW-Ethology device (19b2xxxx UUIDs)

## v2.2 — 2026-06-05

### Field Trip (new game)
- Full game hub: tutorial → 15 hand-authored challenges → procedural stage 4+
- Physics engine: bearing-to-source force model, differential drive conversion
- 15 challenges across 3 stages (single source, two sources, neutral sources)
- Cog scoring: 3 gold (1st attempt), 2 silver (≤3), 1 bronze (solution used)
- Per-sensor policy toggle (attract/repel) with blue/red color coding
- Sensor angle UI: triangle indicator on chassis, drag handle to set angle
- Channel selector: per-sensor, filled color buttons (W/R/G/B)
- Arena preview in robot builder (right panel, replaces wiring editor)
- Force debug display during run: signal strength per sensor, net force vector
- Solution file system: FT_C##_solution.json loaded directly into builder
- J key + number + Enter: jump to any challenge mid-session
- --challenge CLI parameter: py hub.py --challenge 6
- Boundary wall IR behavior: IR sensors see ALL walls including boundaries (by design)
  - This is correct physics; players must account for boundary proximity in sensor design
  - Documented as a teaching point about potential field limit cycles and local minima
- Dynamic sources (moving lights/walls during simulation): PENDING future session

### Engine
- engine/signals.py, engine/vehicle.py, engine/robot_body.py: moved from valentinos/engine/
- engine/builder/: robot_builder.py, wiring_editor.py, wiring_inspector.py moved from valentinos/builder/
- engine/arena/__init__.py: draw_arena and arena utilities now game-independent
- RobotState.chassis_spec: chassis shape flows through to body_corners() for correct rendering
- sensor_physics.py: intensity falloff fixed to use lr*3 (was lr*2), eliminating dead zone
- Sensor angle: stored/loaded/saved in robot.json, displayed as triangle on chassis
- Policy: stored/loaded/saved in robot.json

### Robot Builder
- show_wiring=False mode: canvas fills right panel, arena_preview shown instead
- arena_preview parameter: draws challenge arena in right panel
- Per-sensor channel editing: click channel button while sensor selected
- Auto-select on placement; click any sensor in any tool mode to select
- Ghost connection bug fixed: stale wiring connections purged on sensor delete

### Name That Vehicle (NTV)
- 10 vehicle definitions (5 LDR + 5 IR), dual-column answer UI
- Round progression: 1-10 single sensor, 11-20 multi-source, 21+ mixed
- Replay button between guesses and after round
- View Wiring uses correct sensor names
- All timers 10 seconds
- Back button working

### Known Issues
- RE BLE: still unconfirmed working (see v2.1 notes)
- Field Trip C11-C15 (Stage 3): not yet playtested
- Motor snap points on octagon chassis may display slightly outside boundary (cosmetic)

## v2.4 — 2026-06-08

### Field Trip
- Internal walls are now SOLID with sliding contact (was: passable — robots
  could plow straight through, e.g. The Slalom "succeeded" via the centerline).
  Sliding preserves Flow-around solutions (C7); avoid-penalty retained so
  "don't touch the wall" stays meaningful; reach-the-wall challenges (C3, C8,
  C14) still register contact. Verified: C1-C7 + slalom regression-clean.
- Added per-challenge objective summary in the build panel: ★ reach / ✗ avoid /
  ○ ignore bullets derived from required_reach/avoid/neutral. Stage 1-2 name
  sources plainly; stage 3+ stay deliberately vague to preserve the puzzle
  (e.g. Red Herring shows the decoy as "Ignore a light source (a distraction)"
  without naming which). Fixes the "can't tell the goal" issue.
