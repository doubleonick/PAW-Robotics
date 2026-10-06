# Regression Log

Forensic record of functionality that **worked before the refactor, broke
during it, and was restored**. Distinct from CHANGELOG.md (chronological
feature record): each entry here captures the *before* state, the *cause* of
the break, the *fix*, and whether the fix is **behavior-restoring** (returns to
prior behavior) or **behavior-changing** (restores function but with new
behavior) — so intended changes can be told apart from collateral damage.

Context: the refactor that moved modules into `engine/`, split physics behind
the `PhysicsAdapter` contract, and renamed sensors (RL/RR/PL/PR → IR·L/IR·R/
LDR·C1/C2) inadvertently severed several path/wiring assumptions. VV appeared
to work end-to-end before; these are regressions, not original defects.

Status legend: **FIXED** · **OPEN** · **MONITORING** (fixed, watch for recurrence)

---

## R-001 — BYOV chassis change not reflected in simulation
- **Game:** Valentino's Vehicles (BYOV)
- **Symptom:** Selecting a non-rectangle chassis (e.g. octagon) in the Robot
  Builder, then running, still drew a rectangle robot. Build + wiring otherwise
  correct; the chassis *was* saved correctly to
  `games/valentinos/data/byov/robot.json`.
- **Cause:** `RobotState.chassis_polygon_m` (engine/robot_body.py) read the
  chassis from a path it built from its OWN module location:
  `dirname(dirname(__file__))/data/byov/robot.json`. After robot_body moved to
  `engine/`, that resolves to `<repo-root>/data/byov/robot.json`, which does not
  exist. The read silently fell through to the default-rectangle fallback. The
  hub writes/reads the correct file at `games/valentinos/data/byov/robot.json`;
  the two paths diverged in the move.
- **Fix:** Hub now passes the chassis spec into `RobotState` from memory
  (`_reset_robot`, hub.py), via a new `self._robot_cfg` loaded at startup. The
  renderer no longer depends on the module-relative file path.
- **Type:** Behavior-restoring (correct chassis renders again) + hardening
  (removes the fragile file dependency entirely).
- **Status:** FIXED (2026-06-08). Verified headless: octagon → 8-corner body.

## R-002 — Recording playback drew default chassis
- **Game:** Valentino's Vehicles (BYOV playback)
- **Symptom:** Playback replayed a green rectangle regardless of the robot's
  actual chassis.
- **Cause:** Same root as R-001. The playback path constructed
  `RobotState(x, y, heading)` with no chassis_spec (hub.py `_draw_pb_trace`),
  hitting the same dead file path → rectangle fallback.
- **Fix:** Playback `RobotState` now receives the current robot's chassis_spec.
  (Recordings store pose, not geometry, so the live robot's chassis is used.)
- **Type:** Behavior-restoring.
- **Status:** FIXED (2026-06-08). Shares verification with R-001.

## R-003 — Playback scrubber inert (could not seek)
- **Game:** Valentino's Vehicles (BYOV playback)
- **Symptom:** Scrubber bar rendered but did not respond to click or drag, at
  any cursor position, before or after the recording ended.
- **Cause:** No code connected mouse input on the scrubber to the controller.
  `PlaybackController.seek_frac` existed and `PlaybackHUD` drew `_scrub_rect`
  (and even printed "drag scrubber = seek"), but `byov_playback` mouse events
  were routed only through the button/nav system, which has no scrubber
  hit-test. The link was either dropped in the refactor or never reconnected
  after the HUD/controller were split into engine/playback.py.
- **Fix:** Added `PlaybackHUD.scrub_hit()` and `seek_at()`; routed
  `byov_playback` mouse down/drag/up to them (with a `_pb_scrubbing` drag flag).
  Seeking pauses playback so the cursor stays where dropped.
- **Type:** Behavior-restoring (assuming it worked pre-refactor; if it never
  did, this is a behavior-adding fix — see open question below).
- **Status:** FIXED (2026-06-08). Verified headless: seek + clamp at both ends.

---

## Identified regression *pattern* (drives the cross-game sweep)
Two mechanisms recur and are the search targets for other games:
1. **Module-relative data paths.** Code that builds a filesystem path from
   `__file__` (e.g. `dirname(dirname(__file__))/data/...`) and assumes a data
   directory. Modules that moved into `engine/` now resolve these to the wrong
   place; many "work" only via a silent fallback (R-001/R-002).
2. **Dropped input wiring.** UI elements that DRAW but whose event handling was
   not reconnected after a controller/widget was split out into a shared module
   (R-003).

## Open questions
- R-003 type: confirm whether the scrubber worked pre-refactor (→ restoring) or
  never did (→ adding). User reports VV worked end-to-end before, which favors
  "restoring."
- Whether NTV / Robot Ethology / Field Trip carry the same two patterns —
  pending the cross-game sweep below.

## Cross-game sweep — findings

Swept all games (VV, NTV, Robot Ethology, Field Trip) for the two patterns
above. Result: **no new damaging regressions outside VV.** Details:

### Pattern 1 (module-relative data paths) — full enumeration
Checked every `__file__`-derived path that reaches a data/asset file:
- `engine/robot_body.py` robot.json — the R-001 cause. The broken path still
  exists IN robot_body, but is no longer *reached* because callers (VV hub,
  Field Trip) now pass `chassis_spec` in. **Recommended hardening:** make
  robot_body's file-fallback tolerant/removable so it can't silently mislead a
  future caller. (Not yet done — see open items.)
- `engine/theme.py` settings.json (lines 106/117) — **F-001 below.** Resolves to
  `<repo-root>/settings.json`, which does not exist; theme prefs fall back to
  "phosphor" and persist only after the first `save_theme`. Low severity.
- `engine/professor.py`, `engine/hal/sketch_bridge.py`, NTV `progress.py`,
  Field Trip hub, Ethology hub/launcher, codegen — all resolve to real
  directories. **Clean.**
- **Ethology** robot body: uses `RobotModel` (PyBullet) and reads robot.json
  from `GAME_DIR` (the game's own dir) — resolves correctly. **Clean.**
- **Field Trip** robot body: constructs `RobotState(..., chassis_spec=...)` at
  every site — already does what the VV R-001 fix now does. **Clean** (and is
  the reference implementation VV was brought in line with).

### Pattern 2 (dropped input wiring) — full enumeration
- **Ethology** playback scrubber: hit-tested and routed (hub.py ~1522/1539).
  **Clean** — and confirms R-003 in VV was a genuine regression, since the
  sibling game retained the wiring VV lost.
- **NTV** (`handle_event`), **Field Trip** (button hit-tests) route input
  normally. **Clean.**

### Conclusion
R-001/R-002 (chassis) and R-003 (scrubber) were **VV-specific regressions**;
the same capabilities work correctly in the sibling games. The only other live
instance of either pattern is F-001 (theme persistence), which is low severity
and possibly pre-existing.

---

## Findings (not regressions / needs-confirmation)

## F-001 — Theme preference not persisted (settings.json absent)
- **Game:** All (shared `engine/theme.py`)
- **Symptom (latent):** `load_saved_theme()` reads `<repo-root>/settings.json`,
  which does not exist, so theme always defaults to "phosphor" until the user
  changes a theme (which creates the file via `save_theme`). All callers use the
  same path, so the intended location (repo root) is unambiguous.
- **Open question:** Did theme persistence work before `theme.py` moved into
  `engine/`? If yes → this is a regression (the `dirname(dirname(__file__))`
  base shifted with the move). If the settings file was always created lazily →
  not a regression, just absent-until-first-save. **Needs user confirmation
  before any change** — moving the path could orphan an existing settings file.
- **Status:** OPEN (logged, not fixed — deliberate; do not guess the path).


---

## dev14 (2026-08-05)

### R-14a — Field Trip solution prefabs no longer solve  · **OPEN**
**Before:** all five `FT_CP*_solution.json` prefabs solved their probes; "Show
Solution" demonstrated a working build.
**Cause:** the dev14b world-scale migration (arenas x1.65, then x2.5 to the shared
canvas). The challenges remain solvable — the post-migration sweep found 57/45/9/94
working configs for cp2/cp3/cp4/cp5 — but the specific shipped mountings are no
longer among them.
**Status:** **cp1 still solves; cp2, cp3, cp4, cp5 FAIL.** User-visible: the button
loads a build that then fails the challenge it is the solution to.
**Fix:** regenerate from `tools/pf_sweep.py` once physics is final. Criteria agreed
with the user: legibility first, robustness as tiebreaker, speed only as a floor
(reject anything near the time limit). Deferred so the selection is done once.
**Class:** behavior-changing, pending.

### R-14b — Valentino's robots collided as dimensionless points  · **FIXED**
**Before:** appeared to work; wall overlap was severe but longstanding.
**Cause:** `SimpleDriveAdapter.__init__` took no `body_radius`, and
`_inside_wall()` used only half the wall thickness as its margin. The robot's
CENTRE stopped at the wall face, burying the whole front half.
**Fix:** superseded by polygon collision (R-14e). En route it was briefly
over-corrected to the octagon's 0.0775 inradius against VV's 94x167 mm rectangle
chassis, making the robot float 3 cm clear of side walls — the mirror-image error,
caught by the user. `chassis_collision_radius()` then derived it correctly.
**Class:** behavior-changing (restores collision that never worked).

### R-14c — Arena Editor "Open" did not put the arena into play  · **FIXED**
**Before:** untested workflow; the user was first to try it.
**Cause:** `ArenaBuilder._arena_path` served as both "the file being edited" and
"the session slot the game reads back" (`--arena session_current.json`).
`_load_dialog()` repointed it to the browsed file and left `_dirty = False`, so
**Done** exited without saving, **Save** wrote the browsed file onto itself, and
**Launch** took the wrong path. RE then fell through to the default empty arena.
**Fix:** `_session_path` tracked separately from `_loaded_from`; opening loads
CONTENT into the slot without redirecting it, and marks it dirty. `_request_done`
always writes the slot when one exists.
**Class:** behavior-restoring (intended behaviour never worked).

### R-14d — `load_arena()` missing-file path skipped the canvas fit  · **FIXED**
**Cause:** the early `return dict(DEFAULT_ARENA)` sits before the dev14h fit, so a
missing path yielded a 1.0 x 2.0 arena while every real one was 1.5 x 2.5.
**Class:** behavior-restoring. Introduced and fixed in the same session.

### R-14e — Field Trip simulated a robot turning at half the real rate  · **FIXED**
**Before:** never correct; predates the refactor.
**Cause:** `omega = (right-left) * MOTOR_SPEED / (BODY_RADIUS * 2)` used the body
width (0.155 after the scale correction, 0.094 before) as the wheelbase.
`robots/ethology_v2.json` gives `wheel_base = 0.080`.
**Fix:** `WHEEL_BASE = 0.080` named separately and passed to `PyBulletAdapter`.
**Class:** behavior-changing. **FT turn rate roughly doubles** — large and
immediately visible.

### R-14f — the octagon chassis was 9% too big  · **FIXED**
**Cause:** `robot_builder.CHASSIS["octagon"]["bsquare_m"] = 0.1690` ("70 mm
edges") against `robots/ethology_v2.json` `bounding_square_mm = 155`. The file's
own header comment said 155. 0.155/2 = 0.0775 exactly — RE's `body_radius` IS the
octagon inradius, which is why nothing could be brought into register while this
stood.
**Class:** behavior-changing. The drawn chassis shrinks ~9%.

### R-14g — `PyBulletAdapter` had never been executed  · **FIXED**
**Cause:** ~390 lines written against an assumed `RobotModel` API. Four bugs, all
on the hot path: `reset_pose()` passed a `physicsClientId` it does not accept;
`apply_drive()` did not exist; `load_world()` called neither `ArenaModel.build()`
nor `RobotModel.create_body()`.
**Why it survived:** nothing called the adapter — RE talks to `simulation.py`
directly — and no test existed. `tools/test_pybullet_adapter.py` now does.
**Class:** behavior-restoring.

### R-14h — RE simulator never used the robot's proximity threshold  · **FIXED**
**Cause:** `PROX_THRESHOLD` was 33 in the simulator, 35 in all three firmware
copies, and 15 in the BT mock. Three values, none agreeing.
**Fix:** 20 cm everywhere, per user decision.
**Class:** behavior-changing, deliberate. Open-arena avoidance now triggers much
later; the robot will sometimes reach the bump sensors before avoiding.

### R-14i — VV vehicle demo does not play  · **OPEN**
**Before:** worked.
**Cause:** unknown. Appeared after the `PyBulletAdapter` port (R-14e). The adapter
works in isolation — steps, poses, ray casts and contacts all verified — so it is
not a bare adapter failure. **Not diagnosed.**

### R-14j — RE and VV arenas render with partially occluded walls  · **OPEN**
**Before:** rendered fully.
**Cause:** unknown. Ruled out: VV's arena loads conforming at 1.5 x 2.5;
`arena_scale()` and `world_to_screen()` in `games/valentinos/arena/arena.py` are
byte-identical to the engine's with the same `MARGIN = 28`; the canvas rects are
near-identical. **Not reproduced headlessly.** Field Trip renders correctly and
should become the shared path for all three.
