# CloseTheGap — Project Architecture

## Directory layout

```
CloseTheGap/
│
├── shared/                     Shared infrastructure — used by all games
│   ├── tools/
│   │   └── arena_builder.py    Generic arena editor (no game knowledge)
│   └── theme.py                Colour palette reference copy
│
├── games/ethology/              Robot Ethology game
│   └── engine/                 Engine: pybullet physics, HAL, sensors, theme
│   ├── games/
│   │   └── ethology/           Game logic, hub, hierarchy builder
│   │       └── ethology_arena.json   ← this game's arena
│   ├── tools/                  (legacy location of arena_builder — keep for compat)
│   └── main.py
│
├── valentinos/                 Valentino's Vehicles game
│   ├── engine/                 Analog signal model, vehicle evaluator, physics
│   ├── builder/                Wiring editor UI
│   ├── games/
│   │   ├── byov/               Build Your Own Vehicle (freeplay)
│   │   │   └── valentinos_arena.json   ← this game's arena
│   │   ├── name_that_vehicle/  (future)
│   │   └── hunt_and_forage/    (future)
│   └── main.py
│
└── future_game/                Any new game follows this pattern
    ├── engine/                 Game-specific physics/logic
    ├── games/
    │   └── game_name/
    │       └── game_name_arena.json
    └── main.py
```

## Rules for adding a new game

### 1. Arena files are game-and-mode specific
Each game mode gets its own `<name>_arena.json` inside its own
`games/<mode>/` folder. The arena builder is a shared tool pointed at
that file — it has no knowledge of which game it's serving.

### 2. The arena builder lives in `tools/`
The arena builder lives at `tools/arena_builder.py`.
The arena builder lives at `tools/arena_builder.py`.
The canonical location is `tools/arena_builder.py`.

Search order in any game's simulator:
  1. `$ARENA_BUILDER` environment variable (explicit override)
  2. `<project_root>/tools/arena_builder.py`
  3. Engine locations (engine/)

### 3. Pygame subprocess isolation
The arena builder runs as a subprocess. On Windows, the subprocess
calling `pygame.quit()` on exit uninitialises pygame in the parent
process. Always call `pygame.init()` and rebuild fonts after any
subprocess that uses pygame returns.

The wiring editor (valentinos) runs in-process and must NOT call
`pygame.quit()` — the calling simulator owns the pygame lifecycle.

### 4. Theme
The phosphor-green CRT palette is defined in `engine/engine/theme.py`
(the authoritative source) and copied to `shared/theme.py`.
Games that want a different palette define their own colour constants
inline (as valentinos currently does) or import from shared/theme.py.

### 5. Per-game arena isolation
When a player edits an arena for one game, it must not affect other
games. This is enforced by using separate JSON files. Never share a
single arena.json between two different games.

### 6. Recording format
Valentinos uses `.vvrec` (JSON lines). Robosim uses `.robrec`.
Both are game-specific. If a shared playback tool is built later,
it should auto-detect format from the file extension.

## Naming: when to use a game name, a schema name, or a capability name

Three kinds of name appear in this tree, and mixing them up has already caused a
real architectural problem (see the design note below). The rule:

| kind | example | means |
|---|---|---|
| **capability** | `engine/adapters/`, `engine/arena/`, `engine/sensors/` | shared machinery, no game or schema in view |
| **schema** | Virtual Fields, Braitenberg vehicles, hierarchies | a control vocabulary the player builds in |
| **game** | `games/field_trip/`, `engine/ethology/` | scoped to one game's curriculum, hub, and assets |

**The test that separates schema from game: can two of them be combined in one
robot?** Schemas compose — a potential-field behaviour ranked inside a hierarchy
is a legitimate robot, and making that work is the point of the Maze and Novel
Behavior games. Games do not compose; "Field Trip inside Robot Ethology" is not a
thing. If it can be combined, it is a schema.

Where each is used:

- `games/<game>/` — hubs, challenge scripts, solution prefabs, assets. Always
  game names.
- `engine/<capability>/` — anything more than one game uses, or could. This is
  the **default** for `engine/`.
- `engine/<game>/` — game-specific engine code. Legitimate, but treat it as a
  holding area rather than a home.

**Move trigger.** A schema may live under its originating game's directory until
a *second consumer imports it*. The second import is the signal that the code was
schema-shaped all along. This is a concrete trigger, not an aesthetic judgement —
don't run rename campaigns, and don't pre-emptively hoist things that only one
game uses.

### Design note: why the distinction is load-bearing

`engine/adapters/simple_drive.py` lists the games it serves as "Valentino's
Vehicles (BYOV)" and "Virtual Fields (VF)". The first is a game; the second is
Field Trip's *control schema*. So physics-backend choice was indexed partly by
schema.

That worked while each game used exactly one schema. It breaks the moment schemas
compose: if a potential field is ranked inside a hierarchy, Virtual Fields says
use `SimpleDriveAdapter` and hierarchies say use `PyBulletAdapter`, and the
question has no answer.

The underlying principle the names should keep visible:

> **Physics is a property of the world. Control schema is a property of the
> robot.** A player changing their control code does not change the arena they
> were placed in.

So adapter choice is indexed by game/world, never by schema — which is what makes
"assemble parts, upload code, place the robot, watch" hold together as a model.

### Known exception, recorded rather than fixed

`engine/field_trip/field_physics.py` implements Virtual Fields. Two things are
off about the name, both deliberately left alone for now:

1. It contains **no physics**. Its functions are `compute_sensor_reading`,
   `compute_force`, `force_to_motors`, and three `check_reach_*` goal
   conditions — a controller plus game rules, with no world simulation at all.
   This misnaming is the likely cause of Field Trip's hand-rolled integration
   loop in `hub.py`: the module that sounds like physics isn't, so when world
   stepping was needed there was nothing obvious to reach for and it was written
   inline, duplicating `SimpleDriveAdapter` (with a wheelbase bug the real
   adapter does not have).
2. It is a schema under a game directory, and the move trigger has **already
   fired** — `tools/pf_sweep.py` imports it from outside Field Trip.

Left in place so the dependency is untangled once, when the Maze game needs
Virtual Fields, rather than twice.

## The three layers: chassis, component, world

Constants belong to exactly one of these, and mixing them up has caused real
bugs (a collision radius hardcoded for one chassis; a wheelbase derived from a
body radius).

| layer | scope | lives in |
|---|---|---|
| **Chassis** | per-robot, deliberately many | `RobotConfig` + `robot.json`, `robot_builder.CHASSIS` |
| **Component** | per sensor part | `engine/sensor_physics.py`, firmware `Cog*` classes |
| **World** | per arena, genuinely shared | `engine/arena/world.py` |

Only the third is a global constant. A chassis is a design lever — treaded
vehicles, walkers and smaller robots are intended additions, and each is a new
`robot.json` rather than a code change. A sensor's response curve belongs to the
part, not to the robot it is bolted to or the floor it stands on.

**Consequence:** clearance and solvability are properties of an **(arena,
chassis) pair**, not of an arena. "Is this maze solvable" has no answer without
naming the robot. `arena_check(arena, body_radius)` takes the radius for exactly
this reason.

## What is genuinely shared right now

| Component | Location | Used by |
|---|---|---|
| Arena canvas + constraints | `engine/arena/world.py` | All games |
| Arena JSON schema + loader | `engine/arena/__init__.py` | All games |
| Arena renderer | `engine/arena/__init__.py` | All games |
| Arena builder | `tools/arena_builder.py` | All games |
| Physics contract | `engine/physics_adapter.py` | All games |
| Physics backend | `engine/adapters/pybullet_drive.py` | FT, VV (RE via `simulation.py`) |
| Chassis table + outlines | `engine/builder/robot_builder.py` | All games |
| Robot/chassis config | `engine/config.py` | All games |
| Sensor models | `engine/sensor_physics.py` | FT, VV |
| Theme palette | `engine/theme.py` | All games |
| Layout | `engine/layout.py` | All games |

### Physics: one contract, one backend

`PhysicsAdapter` (`engine/physics_adapter.py`) is the seam:

    step(left, right, dt)   get_pose()   ray_cast()   contacts()

**Above it** is control schema — potential fields, direct wiring, hierarchies.
They all emit the same thing: normalised left/right motor commands. That is why a
potential-field behaviour ranked inside a hierarchy composes: the hierarchy
arbitrates, the winner emits `(left, right)`, and the world does not care where
it came from.

**Below it** is world. Physics is a property of the world; control schema is a
property of the robot. A player changing their code does not change the arena
they were placed in — so **adapter choice is indexed by game/world, never by
schema**.

`dt` is a **primitive duration** — how long the command is held before the next
decision — mirroring firmware `driveProportional(left, right, durationInSeconds)`.
It is not a physics timestep; the engine sub-steps inside it. Robot Ethology's
`ArduinoHAL` is the reference implementation of this contract: `_delay()` records
a resume timestamp in a `TimedAction` and `call_loop()` skips `loop()` until it
expires, with the written servo angles still in force.

### Known duplication and dead code

- `engine/arena.py` — **DEAD**. Permanently shadowed by the `engine/arena/`
  package; never imported. Marked in-file, not yet deleted.
- `games/valentinos/arena/arena.py` — byte-identical duplicate of the engine
  renderer. Should be deleted and its importers repointed.
- `SimpleDriveAdapter` — no remaining callers. Keep as the documented fast
  approximation or delete after a conformance comparison against PyBullet.

## Arena JSON schema (shared across all games)

```json
{
    "width":           1.5,
    "height":          2.5,
    "wall_thickness":  0.05,
    "light_sources":   [{"x": 0.4, "y": 0.4, "radius": 0.25,
                         "intensity": 1.4, "color": "white"}],
    "internal_walls":  [{"x0": 0.0, "y0": 0.5, "x1": 0.5, "y1": 0.5,
                         "thickness": 0.05}],
    "robot_start":     {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
}
```

All dimensions in metres. Origin is arena centre, +y is "up" on screen.

`width`, `height` and `wall_thickness` are fixed by `engine/arena/world.py` —
arenas authored against an older, smaller canvas are fitted uniformly by
`load_arena()` on the way in, so nothing downstream sees a non-conforming arena.

This format is identical across Field Trip, Robot Ethology and Valentino's, and
is what `tools/arena_builder.py` writes and `engine/maze/` generates. **A
challenge cannot tell whether its arena was hand-authored or generated**, which
is the property that makes procedural arenas possible without a second code path.

### Validating an arena

`tools/arena_check.py` answers three questions, in the order the methodology
requires:

1. **Reachable** — is the start unblocked, and is the goal reachable from it?
   Run this FIRST. A sealed chamber passes a "robot gets stuck" test for entirely
   the wrong reason, and once invalidated a whole line of investigation.
2. **Components** — how much of the arena is walled off from everything?
3. **Clearance** — how wide is the narrowest corridor on the best path? This was
   the missing one. A corridor barely wider than the robot, or narrower than the
   sensors' honest range, makes a challenge fail for reasons that have nothing to
   do with control — silently confounding any conclusion drawn from that failure.

Corridor floors, from `engine/arena/world.py`:

| constraint | value | why |
|---|---|---|
| `SENSOR_HONEST_MIN_CORRIDOR` | 0.30 m | below this a side-mounted GP2Y0A21 is inside its fold-back zone and reports a distant surface while touching a near one |
| `PROX_GRADIENT_MIN_CORRIDOR` | 0.36 m | RE's `getData()` saturates at 18 cm, so both sensors pin and there is no gradient to steer on |

These are absolute, not relative to the robot: a smaller chassis does not help,
because the sensor's 10 cm is 10 cm regardless.
