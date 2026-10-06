# PAW Robotics

Perception, Action, World — a suite of educational robotics games plus the
Arduino firmware for the physical robots they model.

Three games (Python/pygame), a shared engine, and Arduino sketches. The
simulator and the firmware are meant to describe **the same robot**; most of
the hard problems in this project come from the two drifting apart.

---

## Setup

**Python 3.12 or 3.13. Not 3.14+** — pygame ships Windows wheels for cp310–cp313
only, so on 3.14 pip tries to build it from source and fails. Check with
`python --version`; list what you have with `py -0`.

```
py -3.12 -m pip install -r requirements.txt
```

**Budget 10–15 minutes**: PyBullet has no Windows wheel at all and always
compiles from source, which needs the Microsoft C++ Build Tools. Build the
wheel once and reuse it:

```
py -3.12 -m pip wheel pybullet --no-deps -w wheels
```

Use ONE interpreter for everything. Most packaging failures here have come from
`python`, `pip` and `pyinstaller` on PATH belonging to different installs.

## Run

```
py -3.12 paw.py                       REM game selector
py -3.12 paw.py --game ethology       REM Robot Ethology
py -3.12 paw.py --game forcefield     REM Field Trip  (key predates the rename)
py -3.12 paw.py --game vehicles       REM Valentino's Vehicles

py -3.12 games\ethology\hub.py        REM direct — paw.py runs games as
                                      REM subprocesses and swallows their output
```

`README.md` has a fuller quick reference, including the standalone build.

---

## Layout

| path | holds |
|---|---|
| `games/` | `field_trip/`, `ethology/`, `valentinos/` — hubs, challenges, assets |
| `engine/` | everything shared. See below. |
| `firmware/` | Arduino sketches. `firmware/shared/` is the source of truth. |
| `robots/` | CAD-derived robot specs — **authoritative for dimensions** |
| `materials/arduino_classes/` | classes copied into every GENERATED sketch |
| `tools/` | arena builder, test harnesses, sweeps |
| `packaging/` | standalone Hierarchy Builder build |

Key engine modules:

| module | owns |
|---|---|
| `engine/arena/world.py` | arena dimensions and corridor constraints — one definition for all games |
| `engine/arena/__init__.py` | arena JSON schema, loader, renderer |
| `engine/physics_adapter.py` | the physics contract |
| `engine/adapters/pybullet_drive.py` | the physics backend all three games use |
| `engine/sensor_physics.py` | sensor models (Field Trip, Valentino's) |
| `engine/sensors/sensor_models.py` | sensor models (Robot Ethology) — **a second implementation** |
| `engine/builder/robot_builder.py` | chassis table and builder UI |
| `engine/config.py` | robot and arena config objects |

---

## Rules that are load-bearing

### 1. `firmware/shared/` is the single source of truth

Arduino requires each sketch folder to contain every `.cpp` it compiles, so the
shared classes are duplicated into all eight projects AND into
`materials/arduino_classes/`.

**Edit `firmware/shared/<file>`, then run the sync. Never edit a project copy —
the next sync silently overwrites it.**

```
py -3.12 firmware\sync_shared.py --check    REM has anything drifted?
py -3.12 firmware\sync_shared.py            REM propagate
```

There were 44 redundant copies before this existed, and copy-paste produced
four separate behavioural bugs — a flattened cruise arc, an inverted light
sensor, a compensating inverted behaviour, and a student-facing copy that
missed all three fixes. `--check` returns non-zero on drift; it belongs in any
pre-commit or pre-package step.

### 2. Arena dimensions come from `engine/arena/world.py`

1.5 × 2.5 m, 5 cm walls, for every game. Arenas authored smaller are fitted on
load. Do not hardcode a size.

Two corridor floors live there too, and they are **absolute, not relative to the
robot** — a smaller chassis does not help, because a sensor's 10 cm is 10 cm:

- `SENSOR_HONEST_MIN_CORRIDOR = 0.30` — below this the IR folds back and lies
- `PROX_GRADIENT_MIN_CORRIDOR = 0.36` — below this RE's proximity saturates

### 3. Physics is a property of the WORLD, control schema is a property of the ROBOT

All three games drive `PhysicsAdapter`. Above it is control (potential fields,
wiring, hierarchies) — every schema emits normalised left/right motor commands,
which is what lets them compose. Below it is world.

**Adapter choice is indexed by game/world, never by schema.**

`step(left, right, dt)` — `dt` is a **primitive duration**, how long the command
is HELD, mirroring firmware `driveProportional(l, r, seconds)`. Not a physics
timestep; the engine sub-steps inside it.

### 4. Naming: game vs schema vs capability

- **capability** (`engine/adapters/`, `engine/arena/`) — shared machinery. The
  default for `engine/`.
- **schema** — a control vocabulary. Schemas COMPOSE: a potential field ranked
  inside a hierarchy is a legitimate robot.
- **game** (`games/field_trip/`) — one game's curriculum and assets. Games do
  not compose.

A schema may live under its originating game until a **second consumer imports
it**; that import is the signal to move it. Concrete trigger, not taste.

### 5. Wire names must match the firmware

`EthologyRobot::BEHAVIOR_NAMES` is the authority, and `setHierarchy()` rejects a
hierarchy **whole** if any name is unknown — a mismatch does not degrade
gracefully. Convention is `verb_target`:

```
escape_front  escape_back  avoid_object  approach_object
avoid_light   approach_light  cruise_straight  cruise_arc
```

---

## Working style

This project has repeatedly had plausible-looking code that had **never been
executed**: a physics adapter with four bugs on its hot path, a module shadowed
by a package so edits did nothing, a codegen emitting method names that did not
exist, a mock server that raises on import. So:

- **Verify with code, not assertion.** Run it. If it cannot be run here, say so
  plainly rather than implying it was checked.
- **Check arena geometry before drawing conclusions about control.** Three
  separate findings were overturned by geometry: a sealed chamber, a corridor
  barely wider than the robot, and an arena too small for the robot's own
  sensor range. `py -3.12 tools\arena_check.py` exists for this.
- **State what is tested vs assumed.** Do not over-claim from a thin search.
- **Record corrections, not just findings**, in `FUTURE_WORK.md`. Several
  entries there are retractions, and they are the most useful ones.
- Nothing in `firmware/` can be compiled in a sandbox. Say when firmware changes
  are unverified.

### Traps

- `SimpleDriveAdapter` has no callers; a `physics_probe.txt` written at runtime instruments whether
  anything reaches it before deletion.
- `engine/bluetooth/mock_bt_server.py` raises `NameError` on import — pre-existing, never used.
- The generated Arduino sketch contains **no BLE**; "Launch Arduino → Bluetooth"
  opens the real firmware instead. The unified two-mode sketch is designed
  (see `FUTURE_WORK.md` dev14v/w) but unbuilt.
- `arduino_export._ensure_headers()` copies `materials/arduino_classes/`, which
  does NOT contain `CogBluetooth.*`.

---

## Test harnesses

```
py -3.12 tools\test_pybullet_adapter.py    REM physics adapter smoke test
py -3.12 tools\arena_check.py              REM reachability, stranded space, clearance
py -3.12 tools\pf_sweep.py --challenge cp3 REM push/pull solvability sweep
py -3.12 firmware\sync_shared.py --check   REM firmware copies in step
```

`pf_sweep` is the only re-runnable source of solvability numbers. **Every
"N of 729" figure predating dev14 is void** — they have been invalidated by a
sealed arena, corridor width, world scale, control rate, a chassis correction,
and polygon physics. Solvability is also per-chassis now: the question has no
answer without naming the robot.

---

## Documentation

| file | for |
|---|---|
| `README.md` | setup, CLI quick reference, layout |
| `ARCHITECTURE.md` | naming rules, the chassis/component/world layers, what is shared |
| `DEVELOPER_GUIDE.md` | where to change what, testing, traps |
| `FUTURE_WORK.md` | running investigation log **including corrections** |
| `REGRESSION_LOG.md` | what broke, why, whether fixed |
| `HANDOFF_dev14.md` | picking the project back up cold |
| `firmware/README.md` | the shared/sync rule, which sketch is which, board caveats |

---

## Open, and worth knowing before touching related code

- **`PROX_THRESHOLD` is 35 in firmware, 20 in the simulator.** Deliberate: the
  raw→cm calibration was derived on an Uno R4 (5 V) and is wrong on a Giga
  (3.3 V). Needs a bench measurement, not a guess.
- **Servo neutral is 1500 µs**, but real servos differ per side.
  `CogServo::setNeutral()` takes measured values; nothing has been measured yet.
- **`Servo.h` does not list `mbed_giga`** among supported architectures.
- Four of five Field Trip solution prefabs fail after the scale migration.
