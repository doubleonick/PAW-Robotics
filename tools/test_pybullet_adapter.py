#!/usr/bin/env python3
"""
test_pybullet_adapter.py — smoke test for engine/adapters/pybullet_drive.py

WHY THIS EXISTS
---------------
PyBulletAdapter shipped ~390 lines of code that had never been executed. It
called RobotModel.reset_pose() with a physicsClientId it does not accept, and
RobotModel.apply_drive(), which did not exist at all. Nothing caught either,
because nothing ever called the adapter: RE talks to simulation.py directly,
and no test exercised it.

These are cheap assertions. Their value is that they run.

    python tools/test_pybullet_adapter.py
"""
from __future__ import annotations
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.config import ArenaConfig, RobotConfig            # noqa: E402
from engine.adapters.pybullet_drive import (                  # noqa: E402
    PyBulletAdapter, _PYBULLET_AVAILABLE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def empty_arena(w=1.0, h=1.4):
    return {"width": w, "height": h, "wall_thickness": 0.05,
            "light_sources": [], "internal_walls": [],
            "robot_start": {"x": 0.0, "y": 0.0, "heading_deg": 90.0}}


def make(arena_dict):
    ac = ArenaConfig.from_dict(arena_dict)
    rc = RobotConfig.from_file(
        os.path.join(os.path.dirname(__file__), "..",
                     "games", "ethology", "robot.json"))
    return PyBulletAdapter(ac, rc), rc


def main():
    print("PyBulletAdapter smoke test\n")
    if not _PYBULLET_AVAILABLE:
        print("  SKIP — pybullet not installed")
        return 0

    a, rc = make(empty_arena())

    # 1. reset_robot must not raise (this was bug #1)
    try:
        a.reset_robot(0.0, 0.0, math.radians(90))
        check("reset_robot() does not raise", True)
    except Exception as e:
        check("reset_robot() does not raise", False, repr(e))
        return 1
    x0, y0, h0 = a.get_pose()
    check("pose after reset is the requested pose",
          abs(x0) < 1e-3 and abs(y0) < 1e-3 and abs(h0 - math.pi / 2) < 1e-2,
          f"({x0:.3f}, {y0:.3f}, {h0:.3f})")

    # 2. step() must not raise (this was bug #2 — apply_drive did not exist)
    try:
        a.step(0.5, 0.5, 0.05)
        check("step() does not raise", True)
    except Exception as e:
        check("step() does not raise", False, repr(e))
        return 1

    # 3. Equal commands drive forward along the heading, not sideways.
    a.reset_robot(0.0, -0.4, math.radians(90))
    for _ in range(20):
        a.step(1.0, 1.0, 0.05)
    x, y, h = a.get_pose()
    check("forward command moves along +y when heading is +90deg",
          y > -0.4 + 0.05 and abs(x) < 0.05, f"({x:.3f}, {y:.3f})")
    check("forward command does not spin the robot",
          abs(((h - math.pi / 2 + math.pi) % (2 * math.pi)) - math.pi) < 0.35,
          f"heading {math.degrees(h):.1f}deg")

    # 4. Sign convention: left<right must yield a LEFT (CCW, +) turn.
    #    Keep the probe SHORT. At wheel_base=0.08 a full differential command
    #    gives omega = (0.35+0.35)/0.08 = 8.75 rad/s — about 1.4 rev/s — so
    #    half a second of turning wraps past 180deg and a naive sign check
    #    reports the opposite direction. (This test failed that way first.)
    TURN_S = 0.05
    a.reset_robot(0.0, 0.0, 0.0)
    a.step(-1.0, 1.0, TURN_S)
    _, _, h_ccw = a.get_pose()
    a.reset_robot(0.0, 0.0, 0.0)
    a.step(1.0, -1.0, TURN_S)
    _, _, h_cw = a.get_pose()
    norm = lambda t: (t + math.pi) % (2 * math.pi) - math.pi
    check("left<right turns counter-clockwise (+heading)", norm(h_ccw) > 0.05,
          f"{math.degrees(norm(h_ccw)):+.1f}deg in {TURN_S}s")
    check("left>right turns clockwise (-heading)", norm(h_cw) < -0.05,
          f"{math.degrees(norm(h_cw)):+.1f}deg in {TURN_S}s")
    check("turn is symmetric about zero",
          abs(norm(h_ccw) + norm(h_cw)) < 0.05,
          f"{math.degrees(norm(h_ccw) + norm(h_cw)):+.2f}deg")

    # 5. Zero command holds position.
    a.reset_robot(0.1, 0.1, 0.0)
    for _ in range(10):
        a.step(0.0, 0.0, 0.05)
    x, y, _ = a.get_pose()
    check("zero command does not drift",
          math.hypot(x - 0.1, y - 0.1) < 0.02, f"({x:.3f}, {y:.3f})")

    # 6. Duration is a PRIMITIVE DURATION: 2x dt must travel ~2x as far.
    a.reset_robot(0.0, -0.4, math.radians(90))
    a.step(1.0, 1.0, 0.05)
    _, y_short, _ = a.get_pose()
    d_short = y_short - (-0.4)
    a.reset_robot(0.0, -0.4, math.radians(90))
    a.step(1.0, 1.0, 0.10)
    _, y_long, _ = a.get_pose()
    d_long = y_long - (-0.4)
    ratio = d_long / d_short if d_short > 1e-6 else 0.0
    check("dt is a duration: doubling it roughly doubles distance",
          1.5 < ratio < 2.6, f"ratio {ratio:.2f}")

    # 7. The boundary wall stops the robot.
    a.reset_robot(0.0, 0.55, math.radians(90))   # near the +y wall of a 1.4m arena
    for _ in range(40):
        a.step(1.0, 1.0, 0.05)
    _, y_wall, _ = a.get_pose()
    check("robot is stopped by the arena boundary",
          y_wall < 0.70 - rc.body_radius + 0.05, f"y={y_wall:.3f}")

    # 8. Throughput, for the SimpleDrive-vs-PyBullet comparison.
    a.reset_robot(0.0, 0.0, 0.0)
    t0 = time.time()
    for _ in range(200):
        a.step(0.4, 0.6, 0.05)
    el = time.time() - t0
    print(f"\n  throughput: 200 primitives of 0.05s in {el:.2f}s "
          f"({200 * 0.05 / el:.1f}x realtime)")

    a.close()
    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
