#!/usr/bin/env python3
"""
sync_shared.py — one source of truth for the shared Arduino classes, without
requiring an Arduino library install.

    python firmware/sync_shared.py --check     # report drift, change nothing
    python firmware/sync_shared.py             # copy shared/ into every sketch

WHY THIS EXISTS
---------------
Every sketch folder must stay self-contained: copy it to a student's laptop,
open it in the Arduino IDE, and it compiles with no setup step. Arduino
enforces this — a sketch compiles the .cpp files sitting next to it.

The cost is duplication. Before this script there were 44 redundant copies of
the shared classes across 8 projects, and copy-paste had silently produced two
behavioural bugs:

  * cruiseLeftArc/cruiseRightArc were refactored to CRUISE_SPEED + ARC_BOOST
    (60/70) in one tree, a 0.52 m turning radius against the verified 0.16 m.
  * CogLight::getData() was inverted in ethology_ble_robot only, so
    avoid_light drove TOWARD light on that robot.

Neither was a coding mistake. Both were what happens when copy-paste is the
sharing mechanism.

So: shared/ holds ONE canonical copy of each shared class. This script pushes
it into the sketch folders. Folders stay self-contained; the copies become
deliberate and, crucially, DETECTABLE — --check fails if any project has
drifted, so an edit made in the wrong place is caught rather than shipped.

RULES
-----
* Edit shared/, never a sketch folder's copy. An edit in the wrong place is
  reverted by the next sync, silently, which is exactly the failure this
  replaces — so run --check before you build.
* A file is copied into a project only if that project ALREADY has it. No
  project gains classes it does not use, and the layout is self-maintaining:
  add an #include and a matching stub file, and sync starts managing it.
* Files NOT in shared/ are per-sketch and untouched: the .ino, CogBluetooth.*
  (BLE transport, ethology only), CogBleLog.* (potential-field logging).

LAYERING (mirrors ARCHITECTURE.md's chassis/component/world split)
------------------------------------------------------------------
  component  CogAnaDigi, CogServo, CogProximity, CogLight, CogVisLight,
             CogCollision, Robot            -- hardware, shared by everything
  schema     EthologyRobot (subsumption), CogPotentialField (force summing)
             -- shared only among the projects using that control schema
  sketch     the .ino, plus its transport
"""
from __future__ import annotations
import argparse
import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(HERE, "shared")


# materials/arduino_classes is NOT a firmware project, but it is another full
# copy of these classes — the one that gets pasted into every sketch the
# Hierarchy Builder GENERATES for a student. Leaving it out of the sync is how
# it ended up carrying the inverted CogLight polarity and the inverted
# approachLight() signs after both were fixed in firmware/, which would have
# shipped `avoid_light` driving TOWARD light in every exported sketch.
EXTRA_CONSUMERS = [
    os.path.normpath(os.path.join(HERE, "..", "materials", "arduino_classes")),
]


def projects() -> list[str]:
    return sorted(
        d for d in os.listdir(HERE)
        if os.path.isdir(os.path.join(HERE, d)) and d != "shared"
        and any(f.endswith(".ino") for f in os.listdir(os.path.join(HERE, d)))
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit non-zero; change nothing")
    args = ap.parse_args()

    if not os.path.isdir(SHARED):
        print(f"ERROR: {SHARED} not found")
        return 1

    shared_files = sorted(f for f in os.listdir(SHARED)
                          if f.endswith((".h", ".cpp")))
    drifted, copied, unmanaged = [], [], []

    targets = [(p, os.path.join(HERE, p)) for p in projects()]
    targets += [(os.path.relpath(d, os.path.join(HERE, "..")), d)
                for d in EXTRA_CONSUMERS if os.path.isdir(d)]

    for proj, pdir in targets:
        have = set(os.listdir(pdir))
        for f in shared_files:
            if f not in have:
                continue                      # this project does not use it
            src, dst = os.path.join(SHARED, f), os.path.join(pdir, f)
            if filecmp.cmp(src, dst, shallow=False):
                continue
            if args.check:
                drifted.append(f"{proj}/{f}")
            else:
                shutil.copy2(src, dst)
                copied.append(f"{proj}/{f}")
        # Anything local that is NOT the sketch or a known per-sketch class
        for f in sorted(have):
            if f.endswith((".h", ".cpp")) and f not in shared_files:
                unmanaged.append(f"{proj}/{f}")

    if args.check:
        if drifted:
            print("DRIFT — these differ from firmware/shared/:\n")
            for d in drifted:
                print(f"   {d}")
            print("\nIf the change belongs to everyone, move it into shared/ and")
            print("re-run without --check. If it is genuinely project-specific,")
            print("that file should not be in shared/ at all.")
            return 1
        print(f"OK — all {len(projects())} projects match firmware/shared/")
    else:
        if copied:
            print(f"Synced {len(copied)} file(s):\n")
            for c in copied:
                print(f"   {c}")
        else:
            print("Nothing to do — every project already matches shared/")

    if unmanaged:
        print("\nPer-sketch files (not shared, not synced):")
        for u in unmanaged:
            print(f"   {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
