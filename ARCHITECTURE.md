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
├── robosim/                    Robot Ethology game
│   ├── robosim/                Engine: pybullet physics, HAL, sensors, theme
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

### 2. The arena builder lives in `shared/tools/`
All games should search `shared/tools/arena_builder.py` first.
The legacy `robosim/tools/arena_builder.py` is kept for backwards
compatibility but `shared/tools/` is the canonical location.

Search order in any game's simulator:
  1. `$ARENA_BUILDER` environment variable (explicit override)
  2. `<project_root>/shared/tools/arena_builder.py`
  3. Legacy robosim locations (fallback)

### 3. Pygame subprocess isolation
The arena builder runs as a subprocess. On Windows, the subprocess
calling `pygame.quit()` on exit uninitialises pygame in the parent
process. Always call `pygame.init()` and rebuild fonts after any
subprocess that uses pygame returns.

The wiring editor (valentinos) runs in-process and must NOT call
`pygame.quit()` — the calling simulator owns the pygame lifecycle.

### 4. Theme
The phosphor-green CRT palette is defined in `robosim/robosim/theme.py`
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

## What is genuinely shared right now

| Component | Location | Used by |
|---|---|---|
| Arena builder | `shared/tools/arena_builder.py` | All games |
| Arena JSON schema | (documented below) | All games |
| Theme palette | `robosim/robosim/theme.py` | Robosim (authoritative) |
| WiFi client | `robosim/robot_wifi_client.py` | Robosim, Valentinos (future) |

## Arena JSON schema (shared across all games)

```json
{
    "width":           2.0,
    "height":          2.0,
    "wall_thickness":  0.05,
    "light_sources":   [{"x": 0.4, "y": 0.4, "radius": 0.25}],
    "internal_walls":  [{"x0": 0.0, "y0": 0.5, "x1": 0.5, "y1": 0.5,
                         "thickness": 0.05}],
    "robot_start":     {"x": 0.0, "y": 0.0, "heading_deg": 90.0}
}
```

All dimensions in metres. Origin is arena centre.
