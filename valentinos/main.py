"""
valentinos/main.py
-------------------
Entry point for Valentino's Vehicles (standalone development tool).

Normal flow:
  Wiring Editor → Simulator → Wiring Editor → ...

Dev shortcuts:
  --vehicle v1|v2a|v2b|v3a|v3b   Load a preset vehicle, skip editor
  --vehicle v2a+v3a               Load a compound preset
  --list-vehicles                 Print all preset names and exit

These presets are the same canonical definitions used by the NTV game,
so testing here is direct truth-grounding for the game.

Examples:
  py -3.12 valentinos/main.py
  py -3.12 valentinos/main.py --vehicle v2a
  py -3.12 valentinos/main.py --vehicle v3b
  py -3.12 valentinos/main.py --vehicle v2b+v3a
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from valentinos.engine.vehicle        import VehicleConfig
from valentinos.engine.signals        import Connection
from valentinos.builder.wiring_editor import WiringEditor
from valentinos.simulator             import Simulator, ARENA_PATH
from valentinos.arena.arena           import load_arena
from valentinos.games.ntv.vehicles    import ALL_VEHICLES, make_compound


# ── Preset loader ──────────────────────────────────────────────────────────────

def load_preset(spec: str) -> VehicleConfig | None:
    """
    Parse a vehicle spec string and return the VehicleConfig.
    Single:   "v2a"       → V2A.config
    Compound: "v2a+v3b"   → make_compound([V2A, V3B])
    Returns None if any key is unrecognised.
    """
    keys = [k.strip().lower() for k in spec.split("+")]
    vdefs = []
    for key in keys:
        if key not in ALL_VEHICLES:
            print(f"[main] Unknown vehicle key: {key!r}")
            print(f"[main] Valid keys: {', '.join(sorted(ALL_VEHICLES))}")
            return None
        vdefs.append(ALL_VEHICLES[key])

    if len(vdefs) == 1:
        return vdefs[0].config
    return make_compound(vdefs)


def list_vehicles():
    print("\nAvailable vehicle presets:")
    print(f"  {'Key':<8}  {'Full name'}")
    print(f"  {'---':<8}  {'---------'}")
    for key, vdef in ALL_VEHICLES.items():
        print(f"  {key:<8}  {vdef.full_name}")
    print("\nCompound examples:")
    print("  v2a+v3a   Cowardice + Love")
    print("  v2b+v3b   Aggression + Explorer")
    print("  v1+v2a    Obstacle Avoidance + Cowardice")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Valentino's Vehicles — standalone dev launcher")
    parser.add_argument(
        "--vehicle", metavar="KEY",
        help="Load a preset vehicle and skip the wiring editor "
             "(e.g. v1, v2a, v3b, v2a+v3b)")
    parser.add_argument(
        "--list-vehicles", action="store_true",
        help="List all preset vehicle keys and exit")
    args = parser.parse_args()

    if args.list_vehicles:
        list_vehicles()
        return

    # Resolve initial config
    if args.vehicle:
        config = load_preset(args.vehicle)
        if config is None:
            sys.exit(1)
        print(f"[main] Loaded preset: {config.name}")
        skip_editor_first = True
    else:
        # Default starting config — shown in editor on first launch
        config = VehicleConfig(
            connections=[
                Connection("PL", "FL", "blue"),
                Connection("PR", "FR", "blue"),
            ],
            name="Vehicle 2a — Cowardice (example)",
        )
        skip_editor_first = False

    import pygame
    pygame.init()

    while True:
        # ── Wiring Editor ─────────────────────────────────────────────────
        if skip_editor_first:
            skip_editor_first = False   # only skip on first iteration
        else:
            editor = WiringEditor(
                initial_config=config,
                title="Valentino's Vehicles — Wiring Editor")
            result = editor.run()

            if result is None:
                print("Exited from wiring editor.")
                pygame.quit()
                break

            config = result

        # ── Simulator ─────────────────────────────────────────────────────
        arena  = load_arena(ARENA_PATH)
        sim    = Simulator(config, arena=arena, arena_path=ARENA_PATH)
        config = sim.run()

        # Simulator called pygame.quit() — reinit for next editor pass
        pygame.init()


if __name__ == "__main__":
    main()
