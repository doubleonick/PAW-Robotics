# PAW-Robotics
A suite of games written in Python that employ behavior based robotics within a PAW systems backdrop to explore ideas in robotics.

---

# Quick reference

Every command uses `py -3.12` because this project needs Python 3.12 or 3.13
and `python` on PATH may be something else — on one dev machine it is 3.14, for
which pygame has no Windows wheel. Substitute your own if it differs; check
with `py -0`.

```
REM ── run ────────────────────────────────────────────────────────────────
py -3.12 paw.py                                REM game selector
py -3.12 paw.py --game ethology                REM Robot Ethology
py -3.12 paw.py --game forcefield              REM Field Trip
py -3.12 paw.py --game vehicles                REM Valentino's Vehicles
py -3.12 games\ethology\hub.py                  REM direct: shows console output

REM ── build the standalone Hierarchy Builder (Windows only) ──────────────
packaging\re_hierarchy_builder\clean_build.bat  REM after any failed attempt
py -3.12 packaging\re_hierarchy_builder\preflight.py
packaging\re_hierarchy_builder\build_windows.bat

REM ── firmware ───────────────────────────────────────────────────────────
py -3.12 firmware\sync_shared.py --check        REM has any copy drifted?
py -3.12 firmware\sync_shared.py                REM propagate firmware/shared/

REM ── checks ─────────────────────────────────────────────────────────────
py -3.12 tools\arena_check.py                   REM all Field Trip arenas
py -3.12 tools\test_pybullet_adapter.py         REM physics smoke test
py -3.12 tools\pf_sweep.py --challenge cp3      REM solvability sweep

REM ── first-time setup ───────────────────────────────────────────────────
py -3.12 -m pip install -r requirements.txt
```

---

# Setting up a new machine

Tested on Windows 11 with Python 3.12. Linux and macOS work for the games;
building the standalone Windows app requires Windows.

## 1. Python

**Python 3.12 or 3.13.** Not 3.14 or newer — pygame ships Windows wheels for
**cp310 through cp313 only**, so on 3.14 pip falls back to building pygame from
source and fails on `distutils.msvccompiler`. Check what `python` actually is:

```
python --version
```

If that reports 3.14+, you have the wrong interpreter on PATH. Use the launcher
to pick an older one and substitute it for `python` in every command below:

```
py -0                       REM list every Python installed
py -3.12 --version
py -3.12 -m pip install -r requirements.txt
```

**Pick one interpreter and use it for everything.** Nearly every packaging
failure in this project has come from `python`, `pip` and `pyinstaller` on PATH
belonging to different installs — a packaged app that died at startup with a
missing pygame, and a build that tried to compile pygame from source under
3.14. `python` means a different thing on different machines; be explicit when
more than one is installed.

If `python` is the version you want, `python -m pip ...` is enough and every
command below works as written. If you have several Pythons installed, use the
launcher to be explicit — `py -3.13 -m pip ...` — and substitute that for
`python` throughout.

## 2. Dependencies

```
py -3.12 -m pip install -r requirements.txt
```

Everything except PyBullet installs in seconds. **On Windows, PyBullet needs a
C++ compiler first** — see the next section.

| Package | Needed for |
|---|---|
| `pygame` | all UI and rendering — **required** |
| `numpy` | robot model maths — **required** |
| `pybullet` | physics for all three games — **required** since dev14 |
| `bleak` | BLE to physical robots — optional |
| `pyserial` | serial/COM to physical robots — optional |
| `matplotlib` | `tools/pf_sim_predict*.py` plots — optional |
| `pyinstaller` | building the standalone app — optional |

The optional imports are deferred, so the games run fine without them. If you
only want the games and no hardware, `pygame numpy pybullet` is enough.

## 2a. Windows: PyBullet needs a C++ compiler

Symptom:

```
error: Microsoft Visual C++ 14.0 or greater is required.
ERROR: Failed building wheel for pybullet
```

**PyBullet ships no Windows wheel.** Checked against PyPI on 2026-08-12: the
last one was pybullet 2.6.9 for Python 2.7 in 2020. Every modern release is
Linux-only (`manylinux`, cp36–cp311), and there is no cp312 or cp313 wheel for
*any* platform. So on Windows, pip always compiles PyBullet from source and
always needs a compiler.

**Downgrading Python does not help on Windows.** There is no Windows wheel for
3.11, 3.10 or anything else recent — the version only matters on Linux.

### Fix: install the Microsoft C++ Build Tools

1. Download **Build Tools for Visual Studio**:
   https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. Run the installer and tick the **"Desktop development with C++"** workload.
   The defaults within it (MSVC v143 and the Windows SDK) are what PyBullet
   needs. Budget several GB and a reboot.
3. Open a **new** terminal so the environment is picked up, then:

```
py -3.12 -m pip install -r requirements.txt
```

The PyBullet compile takes roughly 10–15 minutes. It only happens once.

### Keep the wheel you just paid for

```
py -3.12 -m pip wheel pybullet --no-deps -w wheels
```

That produces `wheels\pybullet-3.2.7-cp313-cp313-win_amd64.whl` — reusable on
any Windows machine with the same Python version, **and no compiler needed
there**:

```
py -3.12 -m pip install wheels\pybullet-3.2.7-cp313-cp313-win_amd64.whl
```

Worth keeping for classroom machines: build once on one machine, copy the wheel
to the rest. A wheel is Python-version and OS specific, so a Linux or 3.12 wheel
will not install on Windows 3.13.

## 3. Verify

```
py -3.12 paw.py
```

The game selector should open. If it does, you are set up.

---

# Launching from the CLI

## The suite

```
py -3.12 paw.py                      # game selector
py -3.12 paw.py --game vehicles      # Valentino's Vehicles
py -3.12 paw.py --game ethology      # Robot Ethology
py -3.12 paw.py --game forcefield    # Field Trip
```

`--game maze` and `--game novel` are reserved for unreleased games.

Note `forcefield` for Field Trip — the key predates the rename.

## Individual games

`paw.py` runs games as subprocesses, so their console output may not reach your
terminal. Launch a hub directly when you need to see prints or tracebacks:

```
py -3.12 games\field_trip\hub.py
py -3.12 games\ethology\hub.py
py -3.12 games\valentinos\hub.py
```

## Field Trip challenge selection

`--game` picks the game, not the challenge. Field Trip has its own flag:

```
py -3.12 games\field_trip\hub.py --challenge 23     # 1-based sequence position
py -3.12 games\field_trip\hub.py --ir-foldback      # model close-range IR fold-back
```

## Standalone tools

```
py -3.12 tools\arena_builder.py                      # arena editor
py -3.12 tools\arena_builder.py --arena path.json    # edit a specific arena
py -3.12 engine\builder\robot_builder.py            # robot builder
```

## Diagnostics and test harnesses

```
py -3.12 tools\test_pybullet_adapter.py              # physics adapter smoke test
py -3.12 tools\pf_sweep.py --challenge cp3           # push/pull solvability sweep
py -3.12 tools\arena_check.py                        # audit all Field Trip challenges
py -3.12 tools\arena_check.py path\to\arena.json      # audit a single arena file
```

Run `arena_check` before drawing conclusions from any arena. Three separate
findings in this project have been overturned by arena geometry rather than
control: a sealed chamber, a corridor barely wider than the robot, and an arena
too small for the robot's own sensor range.

## Environment variables

| Variable | Effect |
|---|---|
| `PAW_RENDER_PROBE=1` | log arena rect, scale and edges to `render_probe.txt` |
| `PAW_BLE_DEBUG=1` | BLE scan and connection traces in the hierarchy builder |
| `SDL_VIDEODRIVER=dummy` | headless pygame (also needs `display.set_mode`) |

---

# Building the standalone Hierarchy Builder

A PyBullet-free classroom app: hierarchy builder plus Arduino export and BLE
upload, no simulator. **Windows only** — PyInstaller does not cross-compile.

```
packaging\re_hierarchy_builder\clean_build.bat      # after any failed attempt
py -3.12 packaging\re_hierarchy_builder\preflight.py
packaging\re_hierarchy_builder\build_windows.bat
```

Output: `..\_output\dist\RE Hierarchy Builder\RE Hierarchy Builder.exe`,
a sibling of the repo folder so build artifacts stay out of the source tree.

Preflight must pass before you build. It checks that the app imports with
PyBullet excluded, that BLE traces are off, that the bundled firmware carries
current constants, and — the one that matters most — that the interpreter
running it has PyInstaller, pygame and pyserial. It prints `sys.executable`;
if that is not the Python you expect, fix that first.

`packaging/re_hierarchy_builder/README.md` has the full detail and a
troubleshooting section.

---

# Repository layout

| Path | Contents |
|---|---|
| `paw.py` | suite launcher and game selector |
| `games/` | the three games: `field_trip/`, `ethology/`, `valentinos/` |
| `engine/` | shared code — see below |
| `tools/` | arena builder, test harnesses, analysis scripts |
| `firmware/` | Arduino sketches for the physical robots |
| `robots/` | CAD-derived robot specs — **the source of truth for dimensions** |
| `materials/` | Arduino classes and icons shipped to classrooms |
| `packaging/` | standalone app build |
| `docs/` | photos, specs, reference material |

Key shared modules:

| Module | Owns |
|---|---|
| `engine/arena/world.py` | arena dimensions and corridor constraints — one definition for all games |
| `engine/arena/__init__.py` | arena JSON schema, loader, renderer |
| `engine/physics_adapter.py` | the physics contract (`step`/`get_pose`/`ray_cast`/`contacts`) |
| `engine/adapters/` | physics backends |
| `engine/sensor_physics.py` | sensor models (Field Trip, Valentino's) |
| `engine/sensors/sensor_models.py` | sensor models (Robot Ethology) |
| `engine/builder/robot_builder.py` | chassis table and robot builder UI |
| `engine/config.py` | robot and arena config objects |

`ARCHITECTURE.md` explains the naming convention and the chassis/component/world
layer model. `DEVELOPER_GUIDE.md` has a "where to change what" table.
`FUTURE_WORK.md` is the running investigation log, including corrections.

---

# Documentation map

| File | What it is for |
|---|---|
| `README.md` | this file — setup, launching, layout |
| `ARCHITECTURE.md` | how the pieces fit; naming rules; what is shared |
| `DEVELOPER_GUIDE.md` | where to change what; testing; known traps |
| `CHANGELOG.md` | release history |
| `REGRESSION_LOG.md` | what broke, why, and whether it is fixed |
| `FUTURE_WORK.md` | investigation log and open questions |
| `HANDOFF_dev14.md` | continuation notes for picking the project back up |
| `FIELD_TRIP_STATUS.md` | Field Trip specifics |
| `packaging/re_hierarchy_builder/README.md` | standalone app build and troubleshooting |

---

# Design notes

The remainder of this file describes the intended shape of the suite. It is a
vision document and parts of it run ahead of what is implemented.


This suite of games uses PyBullet as a 3D backend to create a series of environments and robots that aim to accurately reflect the functionality of physical robots for the purposes of letting people solve a variety of challenges using robotics principles and tools with or without a physical kit of hardware.  The frontend uses PyGame, and thus you have a 3D mathematical backend projected onto a 2D set of graphics and visual interactions.  There are aspects of the game that work around this by showing multiple points of view for a single event or activty.  For example, many of the games have a robot builder application and may use top, side, front and back views for things like sensor placement.

The set of games share some tools and resources.  For example, sensors and actuators are simulated using the same classes and logic, regardless of the game(s) in which they are used.  Similarly, environmental modules, such as light sources and walls are governed the same way across all games.  Each game is developed in such a way as to allow it to be a standalone applicaiton, however.  The gammification elements are intended to be optional, meaning each game may be used as a plainer pedagogical tool, or may be played within the context of a larger whole; a narrative that extends across game play.

The overarching game, the idea or narrative theme that wraps everything together is that you, the player, are being guided by PAW BOt (sp, PAW-Bot?) to learn various behavior based robotics concepts, and unlock games and features that allow you to employ those concepts.  For reference, the games as they currently stand are:

1. Valentino's Vehicles
    a. Introduction: PAW-Bot introduces Valentino Braitenberg's vehicles concept, and demonstrates V1, V2a, V2b, V3a, and V3b, referring to them both by their "V#" designation, and their anthropomorphized designations: object avoidance, cowardice, aggressive, love, explore.
    b. Build Your Own Robot: An open ended game in which you are asked to first, replicate the wiring of some version (altering resistence levels, use of neurons, neuron gain, etc) of the 5 fundamental vehicles.  You are then invited to create vehicles as you like, also modifying the environment as you see fit.
    c. Name That Vehicle: you are shown a sequence of vehicles and must name what you see.  First you are shown, at random, some version of the classic five vehicles.  You are given multiple choice, and have three guesses to determine what you saw.  There are five rounds of this.  Another five rounds combines any two of the fundamental five.  Choices of pairs of behaviors are given, and you must select the right pair.  You have three guesses, and get partial credit (1/N, where N in this case is 2) for guessing each one of the constituent behaviors.  Following this, you have five rounds of guessing combinations of 3 robots.  After that, you may witness any number of behaviors in a single vehicle up to 3.  If you can accomplish the first 10 of these, you unlock Fixed Arbitration.
   d. Hunting and Foraging: This may be played solo, or against another player.  If you choose to be a single player, you will be challenged to create a robot that either forages for light sources, which get consumed as your robot stays by them, or build a robot that hunts some implementation of one of the five fundamental vehicles.  Each time your robot consumes its target, you are presented with a new environment, and potentially new prey, or a greater number of prey.  A counter ticks down 3 minutes each round, stopping when your vehicle depleats its food source, or when the clock reaches 0.  You get a score based on how much time you had left (1 point per second), and how much of the food source(s) you consumed (there will be a formula for this, and 1 point per percentage consumed).


2. Fixed Arbitration: PAW introduces two robots: A and B, and explains that they are governed by fixed arbitration schemes.  As a robot ehtologist, your task is to observe both robots and take notes on what they do.  You will be given the names of eight possible behaviors, any number of which may be determining each robot's behavior.  You get 3 mintues of initial observation (this behavioral sequence will be recorded).  You then use a hierarchy builder to build hypothesis hierarchies for either robot A or robot B.  As you test your hypotheses on one or both robots, you get basic feedback as to whether you guessed correctly or not, and you get an updated look at how many of your 20 total experiments you have left.  If you solve both robots, PAW-Bot contratulates you, and the game ends with a win!  You unlock Force Field Frenzy!

3. Force Field Frenzy!:  PAW introduces the idea of virtual field control.  Certain environmental sources act like attracting fields, while other sources act as repulsors.  The player is assigned increasingly difficult challenges for a given environment, and must use a GUI to create certain magnitudes, and valences of fields that are associated with certain types of environmental objects (e.g. lights, walls, color).  If you can successfully complete 5 challenges, you unlock State your Purpose.

4. State Your Purpose: PAW introduces the idea of state machines.  PAW guides the player through simple two or three state state machines.  You unlock Maze Solver and Novel Behavior.

5. Maze Solver: The player is presented with mazes containing lights at their exits.  Some are just plain lights, some are polarized, some are colored with non-colored decoy lights.  For each maze, the player must use the type of robot (fixed arbitration, virtual field, state machine, other?) specified by PAW-Bot in order to solve the maze.  In later levels, sometimes the player will be told what robot type to use, and sometimes s/he will get the opportunity to use whatever method(s) s/he wants.

6. Novel Behavior: Open ended.  Build a robot by changing its chassis, sensors, actuators and logic to perform new tasks in an environment of your design.

COMMON FEATURES:

1. A game environment or arena with exterior walls forming a 1m x 2m enclosed area.  The use of an arena builder to alter said arena by adding such features as walls and lights (sometimes polarized and or colored).  The game environment would take up the right half of the screen (all game windows being made "full screen" according to local hardware).
2. A control panel taking up the upper half of the left side of the game window.  This would have any buttons or other controls relevant to the current (state of a) game.
3. An "Exit" button that either exits the current game, or the game suite as a whole depending on the window in which it appears.
4. A narrative panel on the lower half of the left side of the game window.  This should provide any game narrative, for example from PAW-Bot.  Any and all characters should have dedicated color pallets and text color in the narration panel that matches that character's color pallet.
5. A robot builder.  This may not apply to every single aspect of every game.  For example, the Robot Ethology robots will be of a fixed architecture.  Likewise, the introductory Braitenberg vehicles will be of a fixed architecture.  However, when it is necessary or permissable to design a robot for a given context, there should be a control button for building a robot similar to how there would be for building an arena.  The builder would have options for chassis, sensors and actuators that match the context of the specific game.  There may be an extensive library of such things, some subset of which may be made available according to context.
6. A robot programmer.  This may or may not fold into the robot builder.  It would be an interface that would allow the player to, among other things: wire a vehicle; build, re-order, and generate (Python emulated) Arduino code for a fixed hierarchy; specify a set of virtual fields; specify a set of states and state transitions for a state machine driven robot; etc.
