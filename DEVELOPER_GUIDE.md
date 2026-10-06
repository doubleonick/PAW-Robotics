# RoboSim Developer Guide

This document explains how to find, understand, and modify the RoboSim codebase.
It is written for someone comfortable with Python but new to this project.

---

## Project structure

```
engine/
├── main.py                        # Entry point — run this to start the sim
├── arena.json                     # Arena layout (size, walls, light sources)
├── robot.json                     # Robot geometry, sensors, motor pins
├── requirements.txt               # Python dependencies
├── sketches/                      # Arduino-style .ino sketch files
│   ├── physics_demo.ino           # Default: wall collision demo
│   ├── demo_sequence.ino          # Timed spin/drive sequence
│   ├── ir_tune.ino                # IR sensor approach demo
│   └── ethology_v2.ino            # Original behaviour hierarchy sketch
└── engine/                       # The simulation package
    ├── config.py                  # Config dataclasses (ArenaConfig, RobotConfig)
    ├── simulation.py              # Main loop: physics + render + HAL
    ├── hal/                       # Arduino Hardware Abstraction Layer
    │   ├── arduino_hal.py         # Mocked Arduino API + .ino transpiler
    │   ├── sketch_bridge.py       # Python versions of C++ robot classes
    │   ├── demo_robot.py          # DemoRobot state machine
    │   ├── ir_tune_robot.py       # IRTuneRobot state machine
    │   └── physics_demo.py        # PhysicsDemo state machine
    ├── sensors/
    │   └── sensor_models.py       # IRSensor, LightSensor, ContactSensor
    ├── robot/
    │   └── robot_model.py         # Physics body, kinematics, pin dispatch
    ├── arena/
    │   └── arena_model.py         # Floor, walls, PyBullet static bodies
    └── renderer/
        └── pygame_renderer.py     # PyGame top-down view + sensor HUD
```

---

## Arena JSON Format

Arena files (e.g. `games/ethology/ethology_arena.json`) define the physical
space the simulation runs in. Each game keeps its own arena file to avoid
cross-game interference.

```json
{
    "width": 2.0,
    "height": 4.0,
    "wall_thickness": 0.05,
    "light_sources": [
        {"x": 0.5, "y": 0.0, "intensity": 1.0, "radius": 0.4}
    ],
    "internal_walls": [
        {"x0": -0.5, "y0": 0.5, "x1": 0.5, "y1": 0.5, "thickness": 0.05}
    ],
    "robot_start": {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
}
```

**Fields:**
- `width`, `height` — arena floor dimensions in metres
- `wall_thickness` — outer boundary wall thickness
- `light_sources` — list of light sources; `x`/`y` in world metres,
  `radius` is the pool radius, `intensity` scales brightness (1.0 = normal)
- `internal_walls` — list of wall segments drawn in the arena builder;
  each is a line from `(x0,y0)` to `(x1,y1)` with given `thickness`
- `robot_start` — default start pose used by `main.py` (single-robot mode);
  `heading_deg` is degrees CCW from east (90 = north)

Use the Arena Builder (`py -3.12 tools/arena_builder.py`) to edit visually.
Each game should maintain its own arena file (e.g. `ethology_arena.json`)
rather than sharing `arena.json` to prevent cross-game interference.

---

## Launcher

The main entry point for the simulation suite:

```
py -3.12 tools/launcher.py
```

Select sketch, arena, and robot files using Browse (cycles through available files). Toggle HUD and IR-only options. Launch the Arena Builder or Simulation from the Workflow panel. The launcher minimises while a tool runs and restores when it closes. Settings are saved automatically to `tools/.launcher_state.json`.

---

## Arena Builder

A standalone tool for designing arenas with a live preview:

```
py -3.12 tools/arena_builder.py
py -3.12 tools/arena_builder.py --arena path/to/my_arena.json
```

**Tabs:**
- **Arena** — width, height, wall thickness
- **Lights** — click canvas to place, click existing to select and edit, Del to delete
- **Walls** — click+drag to draw internal wall segments, click to select, Del to delete
- **Robot** — click canvas to set start position, scroll wheel to rotate heading

**Bottom bar:** New / Open / Save / Launch

Launch saves `arena.json` then starts `main.py` as a subprocess. To use a different entry point, pass `--arena` to that script directly.

---

## How to run

```
py -3.12 main.py
py -3.12 main.py --sketch sketches/demo_sequence.ino
py -3.12 main.py --sketch sketches/ir_tune.ino
py -3.12 main.py --arena arena.json --robot robot.json
py -3.12 main.py --debug
py -3.12 main.py --hud              # show sensor HUD overlays (hidden by default)
py -3.12 main.py --scale 300        # override pixels-per-metre (auto if omitted)
py -3.12 main.py --hud --ir-only    # IR-only HUD panel with ray visualisation
```

Press **Escape** or close the window to quit.

---

## The data flow in one sentence

`.ino sketch` → transpiled to Python → `ArduinoHAL` calls `setup()`/`loop()` →
sketch calls `bot.driveProportional()` → `CogServo` calls `write_pin()` →
`RobotModel` sets servo angles → `DifferentialDrive` applies forces in PyBullet →
physics steps → `RobotModel.step()` reads pose + updates sensors →
sensors route back through `read_pin()` → next `loop()` call reads them.

---

## Configuration files

### `arena.json`

Controls the physical environment.

```json
{
    "width": 2.0,
    "height": 4.0,
    "wall_thickness": 0.05,
    "light_sources": [
        { "x": 0.5, "y": 0.5, "intensity": 1.0, "radius": 0.35 }
    ]
}
```

All dimensions are in **metres**. The arena origin `(0,0)` is the centre.
`+Y` is forward (up on screen), `+X` is right.

To change arena size: edit `width` and `height`.
To add a light source: add an entry to `light_sources`.
To remove all lights: set `"light_sources": []`.

### `robot.json`

Controls the robot's physical properties and sensor layout.

Key fields:

| Field | Description |
|---|---|
| `body_radius` | Robot collision circle radius in metres |
| `wheel_base` | Left-to-right wheel separation in metres |
| `total_mass_kg` | Total robot mass for physics |
| `motor.left_pin` / `motor.right_pin` | Servo channel numbers (match sketch) |
| `sensors` | Dictionary of sensor configs (see below) |

#### Sensor config fields

Each sensor in `robot.json` has:

| Field | Description |
|---|---|
| `type` | `"ir"`, `"light"`, or `"contact"` |
| `mount` | `[x, y]` offset from robot centre in metres. `+x` = right, `+y` = forward. Raycasting sensors (IR) automatically exclude hits on the robot's own body. |
| `angle` | Degrees CCW from forward (`+Y`). `0` = straight ahead, `45` = left-forward, `-45` = right-forward |
| `pin` | Arduino pin label, e.g. `"A0"`, `"2"` |
| `noise_stddev` | Sensor noise (0 = perfect, 3.0 = realistic Sharp IR) |
| `hud_color` | `[R, G, B]` colour for the HUD overlay |

To move a sensor: change its `mount` values.
To repoint a sensor: change its `angle`.
To add a sensor: add a new entry and give it an unused `pin`.

---

## Sketches

Sketches in `sketches/` are `.ino` files that mirror what runs on the physical
Arduino. They are transpiled to Python at runtime by `arduino_hal.py`.

The transpiler handles:
- `constexpr` / typed variable declarations → Python assignments
- `void setup()` / `void loop()` → `def setup()` / `def loop()`
- `Serial.begin()` → `pass`
- `delay(ms)` → non-blocking timer (does not freeze the simulation)

### Writing a new sketch

> **Note for Windows users:** Save `.ino` files with any line ending style (CRLF or LF) — the transpiler normalises them automatically.


1. Create `sketches/my_sketch.ino`
2. At the top, declare your robot class and servo channels:
   ```cpp
   #include "EthologyRobot.h"
   EthologyRobot bot;
   constexpr uint8_t LEFT_SERVO_CHANNEL  = 6;
   constexpr uint8_t RIGHT_SERVO_CHANNEL = 5;
   ```
3. Write `setup()` and `loop()` as you would for Arduino
4. Run with `py -3.12 main.py --sketch sketches/my_sketch.ino`

### Available robot classes in sketches

| Class | Description |
|---|---|
| `EthologyRobot` | Full sensor suite + behaviour hierarchy |
| `DemoRobot` | Timed spin/drive/reverse sequence |
| `IRTuneRobot` | Proportional speed ramp toward wall |
| `PhysicsDemo` | Contact-triggered wall collision demo |

### Available Arduino functions

`pinMode`, `digitalWrite`, `digitalRead`, `analogWrite`, `analogRead`,
`delay`, `millis`, `micros`, `map`, `constrain`, `abs`, `min`, `max`,
`Serial.begin`, `Serial.print`, `Serial.println`

### `delay()` is non-blocking

`delay(500)` records a resume time and returns immediately. The physics
engine and renderer keep running during the delay. The next `loop()` call
is suppressed until the timer expires — exactly replicating Arduino blocking
behaviour without freezing the simulation.

---

## Adding a new robot class

If you want a new behaviour (e.g. a wall-follower), the cleanest approach is:

1. Create `engine/hal/my_robot.py` — copy `demo_robot.py` as a template
2. Implement `begin()`, `runSequence()`, and `get_state_label()`
3. Register it in `sketch_bridge.py` inside `SketchBridge.install()`:
   ```python
   from engine.hal.my_robot import MyRobot
   # add to the return dict:
   "MyRobot": MyRobot,
   ```
4. Reference it in your sketch:
   ```cpp
   #include "MyRobot.h"
   MyRobot bot;
   ```

---

## Physics tuning

Physics parameters are in `engine/robot/robot_model.py` inside `DifferentialDrive`:

| Parameter | Default | Effect |
|---|---|---|
| `MAX_SPEED` | 0.35 m/s | Top speed at 100% power |
| `MAX_FORCE` | 8.0 N | Peak motor force |
| `VELOCITY_GAIN` | 25.0 | How aggressively the motor chases target speed |
| `ANGULAR_GAIN` | 0.6 | How aggressively the robot corrects heading |

And in `engine/robot/robot_model.py` inside `create_body()`:

| Parameter | Default | Effect |
|---|---|---|
| `lateralFriction` | 0.7 | Grip on floor |
| `spinningFriction` | 0.02 | Resistance to spinning on the spot |
| `restitution` | 0.1 | Bounciness on wall contact |
| `linearDamping` | 0.5 | Air/floor drag on linear motion |
| `angularDamping` | 0.8 | Drag on rotation |

Wall friction is in `engine/arena/arena_model.py` inside `_make_static_box()`.

---

## Sensor tuning

IR sensor parameters are in `engine/sensors/sensor_models.py` inside `IRSensor`:

| Parameter | Default | Description |
|---|---|---|
| `RAW_MIN` | 120 | Empirical ADC reading at max range (80 cm) |
| `RAW_MAX` | 720 | Empirical ADC reading at min range (~10 cm) |
| `DIST_MIN` | 0.10 m | Sensor minimum reliable distance |
| `DIST_MAX` | 0.80 m | Sensor maximum reliable distance |
| `BEAM_HALF_DEG` | 5.0° | Half-angle of detection cone (Sharp GP2Y0A21YK0F) |

Per-sensor noise is set in `robot.json` under `noise_stddev`.

---

## Display and frame rate

Display settings are in `engine/renderer/pygame_renderer.py` at the top of
`PyGameRenderer.__init__()`. Key values:

| Setting | Location | Description |
|---|---|---|
| `screen_w`, `screen_h` | `__init__` | Window size in pixels |
| `hud_panel_w` | `__init__` | Left sidebar width in pixels |
| Render rate | `engine/simulation.py` | `RENDER_DT = 1.0 / 30.0` (30 Hz) |
| Physics rate | `engine/simulation.py` | `PHYSICS_DT = 1.0 / 120.0` (120 Hz) |
| Font sizes | `init()` | `SysFont("consolas", 20)` etc. |

To change window size: edit `screen_w` and `screen_h` in `__init__`.
To change frame rate: edit `RENDER_DT` in `simulation.py`.

---

## Coordinate conventions

| Convention | Value |
|---|---|
| World origin | Centre of arena |
| Forward direction | `+Y` (up on screen) |
| Right direction | `+X` (right on screen) |
| Heading `0°` | Facing `+X` (east) |
| Heading `90°` | Facing `+Y` (north, up screen) |
| Physics units | Metres, kilograms, seconds |
| Sensor mount units | Metres from robot centre |
| Sensor angle units | Degrees CCW from robot forward (`+Y`) |

---

## Common tasks quick reference

| Task | Where to look |
|---|---|
| Change arena size | `arena.json` → `width`, `height` |
| Add a light source | `arena.json` → `light_sources` |
| Move a sensor | `robot.json` → sensor `mount` |
| Repoint a sensor | `robot.json` → sensor `angle` |
| Change robot speed | `robot_model.py` → `DifferentialDrive.MAX_SPEED` |
| Change wall bounciness | `arena_model.py` → `restitution` |
| Change window size | `pygame_renderer.py` → `screen_w`, `screen_h` |
| Change frame rate | `simulation.py` → `RENDER_DT` |
| Write a new behaviour | New `.ino` sketch + (optionally) new Python robot class |
| Load a different sketch | `py -3.12 main.py --sketch sketches/my_sketch.ino` |
| Enable debug logging | `py -3.12 main.py --debug
py -3.12 main.py --hud              # show sensor HUD overlays (hidden by default)
py -3.12 main.py --scale 300        # override pixels-per-metre (auto if omitted)
py -3.12 main.py --hud --ir-only    # IR-only HUD panel with ray visualisation` |

---

## Dependencies (dev14 onward)

**PyBullet is now required.** All three games collide through
`engine/adapters/pybullet_drive.PyBulletAdapter`.

```
pip install pybullet --break-system-packages
```

It is **source-only** — no prebuilt wheel exists on PyPI for any platform — and
takes roughly 13 minutes to compile on a single core. Build a wheel once and keep
it:

```
pip wheel pybullet --no-deps -w ./wheels
pip install ./wheels/pybullet-3.2.7-*.whl --break-system-packages
```

If a build appears to die silently, note that a shell command timeout kills its
whole process group. Detach it: `setsid nohup pip wheel ... &`, then poll.

Also required: `pygame`. Headless work needs
`SDL_VIDEODRIVER=dummy`, `pygame.init()` **and** `pygame.display.set_mode(...)` —
the `set_mode` call is not optional.

## Where to change what (dev14 additions)

| Change | Where |
|---|---|
| Arena size, wall thickness, grid, corridor floors | `engine/arena/world.py` |
| Chassis dimensions and outlines | `engine/builder/robot_builder.py` `CHASSIS` |
| Robot dimensions from CAD | `robots/ethology_v2.json` (source of truth) |
| Physics backend for a game | that game's adapter construction |
| Sensor response curves | `engine/sensor_physics.py` |
| RE proximity threshold | `PROX_THRESHOLD`, kept in step across sim, all three firmware copies and the BT mock |

## Testing

| Tool | What it checks |
|---|---|
| `tools/test_pybullet_adapter.py` | adapter smoke test, 11 assertions |
| `tools/arena_check.py` | reachability, stranded space, corridor clearance |
| `tools/pf_sweep.py` | push/pull solvability sweep over the builder's real config space |

**Run `arena_check` before claiming anything about an arena.** Three separate
conclusions in this project's history have been overturned by arena geometry
rather than control: a sealed chamber, a corridor barely wider than the robot,
and an arena too small for the robot's own sensor range.

## Traps

- `engine/arena.py` is **dead code**, permanently shadowed by the
  `engine/arena/` package. Editing it does nothing. The live file is
  `engine/arena/__init__.py`.
- `games/valentinos/arena/arena.py` is a byte-identical duplicate of the engine
  renderer.
- `SimpleDriveAdapter` has no remaining callers.
