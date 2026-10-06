# PAW Robotics — Arduino firmware

## firmware/shared/ is the single source of truth

Every sketch folder must be self-contained: hand it to a student, open it in
the Arduino IDE, and it compiles with no setup step. Arduino enforces that — a
sketch compiles the `.cpp` files sitting next to it. So the shared classes are
duplicated into each project.

`firmware/shared/` holds the canonical copy. The duplicates still exist, but
they are now maintained rather than accidental:

```
python firmware/sync_shared.py --check     # report drift, change nothing
python firmware/sync_shared.py             # copy shared/ into every sketch
```

**Edit `firmware/shared/<file>`, then run the sync.** Never edit a project copy
directly — the next sync silently overwrites it.

A file is copied into a project only if that project already has one of that
name, so no project gains or loses files. To give a project a new shared class,
copy it in once by hand; the script maintains it thereafter.

### Why

There were 44 redundant copies across 8 projects, and copy-paste had produced
two behavioural bugs, neither a coding mistake:

- **cruise arc flattened.** A refactor to `CRUISE_SPEED + ARC_BOOST` (60/70)
  reached one tree only. Turning radius 0.52 m against the verified 0.16 m —
  too wide to turn inside a corridor the robot fits through.
- **CogLight polarity inverted** in `ethology_ble_robot` alone, flipping every
  light gradient. `approachLight()` was inverted too and the two cancelled, but
  `avoidLight()` was not — so it drove **toward** light.

Several apparent "three different versions" of a header were CRLF/LF splits
with identical content. The sync normalises line endings to LF.

## Layout

| | |
|---|---|
| `shared/` | hardware abstraction + robot classes: `CogAnaDigi`, `CogServo`, `CogProximity`, `CogLight`, `CogVisLight`, `CogCollision`, `Robot`, `EthologyRobot`, `CogPotentialField` |
| `<project>/*.ino` | per sketch, never shared |
| `ethology_ble_robot/CogBluetooth.*` | per sketch — BLE transport |
| `potential_field_ble/CogBleLog.*` | per sketch |

## Which sketch is which

| project | for |
|---|---|
| **`ethology_ble_robot`** | **the classroom robot.** Receives a hierarchy over BLE from the Hierarchy Builder. |
| `ethology_standalone` | same behaviours, hierarchy hardcoded in `loop()`. No BLE, no host. |
| `potential_field_ble` / `_standalone` | Field Trip's physical counterpart. Reference for the simulator's PF model. |
| `colorpal_*`, `drivetrain_baseline` | bench diagnostics for hardware bring-up. Not part of any game. |

## The display is a compile-time option

`ethology_ble_robot.ino` supports the GIGA Display Shield HUD, but does not
require it:

```cpp
#define PAW_USE_DISPLAY 0   // default — no display, compiles on any board
#define PAW_USE_DISPLAY 1   // GIGA HUD; needs CogDisplay.h/.cpp + Arduino_H7_Video
```

At `0` a no-op shim stands in, so every `display.` call site compiles away to
nothing. This is deliberately an option rather than a second copy of the
sketch — two lineages of one firmware is how both bugs above happened.
`CogDisplay.h/.cpp` are **not** in this repo; drop them in when using `1`.

## Light sensor polarity — check this when pairing new hardware

`CogLight::getData()` returns **0 = bright, 100 = dark**. The LDR on this robot
is in a divider that reads HIGH in the dark, and `analyzeData()` maps
`[0,1023] -> [100,0]` to suit it. Every light behaviour in `EthologyRobot` is
calibrated against that convention and verified on hardware.

**Sensors that rise with brightness — most breakout modules, phototransistor
boards, an LDR pulled the other way — will invert every light behaviour:**
`approach_light` flees, `avoid_light` homes in.

The fix is one line in `CogLight::analyzeData()`:

| wiring | map |
|---|---|
| rising in dark (this robot) | `map(raw, 0, 1023, 100, 0)` |
| rising in light (many others) | `map(raw, 0, 1023, 0, 100)` |

Do **not** fix it by swapping `approachLight()` and `avoidLight()`, and do not
re-derive their motor commands — those were each got wrong twice by reasoning
from the gradient sign and are now correct.

To tell which you have: `Serial.println(rightLight.getData())` and shine a
torch at the right sensor. The number must go DOWN toward 0.

The simulator mirrors this in `engine/sensors/sensor_models.LightSensor`; if
you change one, change both or the game teaches the opposite of the robot.

## Board support

Everything here is calibrated for the **Uno R4 WiFi** (see
`robots/hardware_profiles.json`). Two things change on a **Giga R1**:

- **`Servo.h` does not list `mbed_giga`** among its architectures. Use the
  PCA9685 constructor (`EthologyRobot(Adafruit_PWMServoDriver&)`) instead.
- **3.3 V logic, not 5 V.** The same sensor voltage produces a much larger raw
  reading, so `CogProximity`'s `[120,720] -> [60,18] cm` map — and therefore
  every distance the robot reports, and `PROX_THRESHOLD` with it — is wrong
  until re-measured on that board.

## Wire protocol

`ethology_ble_robot` and the Hierarchy Builder must agree on behaviour names.
`EthologyRobot::BEHAVIOR_NAMES` is the authority; `{"cmd":"behaviors"}` lets a
host discover it. `setHierarchy()` rejects a hierarchy **whole** if any name is
unrecognised, so a mismatch does not degrade gracefully.

The eight names, convention `verb_target`:

```
escape_front   escape_back
avoid_object   approach_object
avoid_light    approach_light
cruise_straight cruise_arc
```

## Building the standalone Hierarchy Builder

Full instructions: **`packaging/re_hierarchy_builder/README.md`**, and a
summary in the root `README.md` under "Building the standalone Hierarchy
Builder". Short form, from the repo root on Windows:

```
packaging\re_hierarchy_builder\clean_build.bat      REM after any failed attempt
python packaging\re_hierarchy_builder\preflight.py
packaging\re_hierarchy_builder\build_windows.bat
```

Preflight must pass first — it checks the interpreter running it has
PyInstaller, pygame and pyserial, that the app imports with PyBullet excluded,
and that the bundled firmware carries current constants.

---

# Robot Ethology — Reference Code (for instructor teaching)

This folder holds the complete, vetted Arduino code for the Robot Ethology lab,
in two forms. Both use the **same** robot classes (`EthologyRobot` and the
`Cog*` sensor/motor classes), so they behave identically — they differ only in
how the hierarchy gets onto the robot.

## `ethology_standalone/` — the "teach the code" version (no Bluetooth)

A single sketch that runs **one fixed behavior hierarchy** directly at power-up,
with no BLE and no host computer. Open `ethology_standalone.ino` — the `loop()`
is the whole lesson: it checks each behavior top-to-bottom and runs the first
whose condition is met (subsumption). This is the plain-code form of the
hierarchy the students studied, meant to be read and explained line by line.

The hierarchy baked in is the default lab target:
`escape_front → avoid_object → approach_light → cruise_straight`.
To teach a different hierarchy, reorder / swap the `if` blocks in `loop()` to
match — the method names map directly to the behavior names.

## `ethology_ble_robot/` — the live lab robot (Bluetooth)

The full BLE firmware the robots actually run during the lab. It receives a
hierarchy over Bluetooth from the Hierarchy Builder and executes it. Same robot
classes as the standalone version, plus `CogBluetooth` for the BLE link.

### Setting robot identity (Robot A vs Robot B)

So the Hierarchy Builder can target a specific robot when **both are on**, each
board advertises a distinct name. In `ethology_ble_robot.ino`, in `setup()`,
set the identity by leaving one line uncommented:

```cpp
const char* ROBOT_NAME = "PAW-RobotA";
// const char* ROBOT_NAME = "PAW-RobotB";
```

Flash one robot as `PAW-RobotA`, the other as `PAW-RobotB` (comment the first
line and uncomment the second). The Builder's "Scan" will then list both, and
you choose which to send to.

## Which behaviors exist

`escape_front`, `escape_back`, `avoid_object`, `approach_object`, `approach_light`,
`avoid_light`, `cruise_straight`, `cruise_arc` — these map to methods on
`EthologyRobot` (e.g. `approach_light` → `approachLight()`,
`avoid_object` → `avoidObject()`).
