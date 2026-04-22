"""
main.py
--------
RoboSim entry point.

Usage
-----
  python main.py
  python main.py --sketch sketches/ethology_v2.ino
  python main.py --arena arena.json --robot robot.json --sketch sketches/ethology_v2.ino
  python main.py --debug
"""

import argparse
import logging
import os
import sys

# Ensure package is importable from this directory
sys.path.insert(0, os.path.dirname(__file__))

from robosim.config import ArenaConfig, RobotConfig
from robosim.simulation import Simulation


def main():
    parser = argparse.ArgumentParser(description="RoboSim — Arduino robot simulator")
    parser.add_argument("--arena",  default="arena.json",
                        help="Path to arena JSON config (default: arena.json)")
    parser.add_argument("--robot",  default="robot.json",
                        help="Path to robot JSON config (default: robot.json)")
    parser.add_argument("--sketch", default="sketches/ldr_ethology.ino",
                        help="Path to Arduino sketch .ino file")
    parser.add_argument("--debug",  action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--hud", action="store_true",
                        help="Show sensor HUD overlays (hidden by default)")
    parser.add_argument("--record", default="",
                        help="Save recording to this path")
    parser.add_argument("--scale", type=float, default=None,
                        help="Pixels per metre (auto-computed if omitted)")
    parser.add_argument("--ir-only", action="store_true",
                        help="IR-focused HUD panel (use with --hud)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    # Load configs
    if not os.path.exists(args.arena):
        logging.error("Arena config not found: %s", args.arena)
        sys.exit(1)
    if not os.path.exists(args.robot):
        logging.error("Robot config not found: %s", args.robot)
        sys.exit(1)

    arena_cfg = ArenaConfig.from_file(args.arena)
    robot_cfg = RobotConfig.from_file(args.robot)

    sketch_path = args.sketch if os.path.exists(args.sketch) else None
    if args.sketch and not sketch_path:
        logging.warning("Sketch not found: %s — running without sketch", args.sketch)

    import math
    # Use robot start pose from arena.json if present
    import json as _json
    _arena_raw = _json.load(open(args.arena))
    _rs = _arena_raw.get("robot_start", {})
    _start_x   = _rs.get("x", 0.0)
    _start_y   = _rs.get("y", 0.0)
    _start_hdg = math.radians(_rs.get("heading_deg", 90.0))

    sim = Simulation(
        arena_cfg,
        arena_name=os.path.basename(args.arena),
        robot_name=os.path.basename(args.robot),
        show_hud=args.hud,
        scale_px_per_m=args.scale,
        ir_only=getattr(args, "ir_only", False),
    )
    sim.add_robot(
        robot_cfg,
        sketch_path=sketch_path,
        start_x=_start_x,
        start_y=_start_y,
        start_heading=_start_hdg,
    )
    sim.setup()
    if getattr(args, "record", ""):
        import os as _os
        rec_path = args.record if os.path.isabs(args.record) \
                   else os.path.join(os.path.dirname(
                       os.path.abspath(__file__)), args.record)
        sim.start_recording(rec_path)
    sim.run()
    if getattr(args, "record", ""):
        sim.stop_recording()


if __name__ == "__main__":
    main()
