# RoboSim

A cross-platform Arduino robot simulator with a PyBullet physics backend and PyGame top-down renderer.

## Quick start

### 1 — Install Python 3.10+

- **Windows**: https://python.org/downloads — tick "Add to PATH"
- **macOS**: `brew install python` or https://python.org/downloads
- **Linux**: `sudo apt install python3 python3-pip` (or your distro's equivalent)

### 2 — Install dependencies

```bash
cd robosim
pip install -r requirements.txt
```

**Python 3.14 + 3.12 side-by-side (Windows):** use `py -3.12` to target 3.12 explicitly:
```bash
py -3.12 -m pip install -r requirements.txt
```

No conda, no Docker required.

### 3 — Run

```bash
python main.py
```

**Python 3.14 + 3.12 side-by-side (Windows):**
```bash
py -3.12 main.py
```

With options:
```bash
py -3.12 main.py --sketch sketches/ir_tune.ino
py -3.12 main.py --sketch sketches/demo_sequence.ino
py -3.12 main.py --arena arena.json --robot robot.json --sketch sketches/my_sketch.ino
py -3.12 main.py --debug
```

Press **Escape** or close the window to quit.

---

## Project structure

```
robosim/
├── main.py                        # Entry point
├── arena.json                     # Default arena config
├── robot.json                     # Default robot config (derived from CAD)
├── requirements.txt
├── sketches/
│   └── ethology_v2.ino            # Example sketch (mirrors your Arduino code)
└── robosim/
    ├── config.py                  # ArenaConfig, RobotConfig dataclasses
    ├── simulation.py              # Top-level sim loop
    ├── hal/
    │   ├── arduino_hal.py         # Mocked Arduino API + sketch loader
    │   └── sketch_bridge.py      # Python equivalents of C++ sensor/robot classes
    ├── sensors/
    │   └── sensor_models.py       # IRSensor, LightSensor, ContactSensor
    ├── robot/
    │   └── robot_model.py         # RobotModel, DifferentialDrive kinematics
    ├── arena/
    │   └── arena_model.py         # ArenaModel: walls, floor, light sources
    └── renderer/
        └── pygame_renderer.py     # PyGame top-down view + sensor HUD
```

---

## Sensor HUD

Each sensor displays a semi-transparent indicator at its physical location on the robot:

| Sensor | Indicator | Scales with |
|--------|-----------|-------------|
| IR proximity | Green wedge/cone | Object proximity (brighter/longer = closer) |
| Ambient light (LDR) | Yellow circle | Light intensity (larger = brighter) |
| Contact (bump) | Red circle | Triggered = bright, clear = dim |

All indicators remain visible at minimum size/opacity even at zero reading.

---

## Adding a new sketch

1. Place your `.ino` file in `sketches/`
2. Run: `python main.py --sketch sketches/your_sketch.ino`

The HAL automatically provides `setup()` and `loop()`, all Arduino API functions,
and the full `EthologyRobot` / `Robot` / sensor class tree.

---

## Customising the arena

Edit `arena.json`:
```json
{
    "width": 2.0,
    "height": 2.0,
    "wall_thickness": 0.05,
    "light_sources": [
        { "x": 0.5, "y": 0.5, "intensity": 1.0, "radius": 0.35 }
    ]
}
```

All dimensions are in **metres**.
