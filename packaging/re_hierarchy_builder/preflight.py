#!/usr/bin/env python3
"""
preflight.py — check the standalone build will work BEFORE running PyInstaller.

Run from the repo root:

    python packaging/re_hierarchy_builder/preflight.py

A PyInstaller build takes minutes and its failures are cryptic. Every check here
is one that has actually bitten, or that dev14 newly put at risk.

The big one: the standalone is deliberately **PyBullet-free** (see the spec's
`excludes`). dev14 made PyBullet a hard dependency of all three GAMES, so the
builder importing it by accident would silently add ~100 MB and a native
dependency to a classroom app — or fail on a machine without it.
"""
from __future__ import annotations
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


class _Blocker:
    """Refuse pybullet imports, exactly as the frozen build will."""
    def find_module(self, name, path=None):
        if name.split(".")[0] in ("pybullet", "pybullet_data"):
            return self

    def load_module(self, name):
        raise ImportError(f"{name} is excluded from the standalone build")


def main() -> int:
    print("RE Hierarchy Builder — build preflight\n")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    # 1. Everything the app needs must import with pybullet unavailable.
    sys.meta_path.insert(0, _Blocker())
    try:
        import pygame
        pygame.init()
        pygame.display.set_mode((100, 100))
        import games.ethology.hierarchy_builder as hb
        import games.ethology.arduino_export            # noqa: F401
        import games.ethology.codegen                   # noqa: F401
        import engine.theme                             # noqa: F401
        import app_paths                                # noqa: F401
        import intro_screens                            # noqa: F401
        import re_hierarchy_builder_app                 # noqa: F401
        check("imports cleanly with PyBullet excluded", True)
        check("HierarchyBuilder class present", hasattr(hb, "HierarchyBuilder"))
    except Exception as e:
        check("imports cleanly with PyBullet excluded", False, repr(e))
        return 1
    finally:
        sys.meta_path.pop(0)

    # 2. BLE debug traces must be off for a classroom build.
    check("BLE debug traces quiet by default",
          not hb._BLE_DEBUG,
          "set PAW_BLE_DEBUG=1 to re-enable during bring-up")
    if os.environ.get("PAW_BLE_DEBUG"):
        check("PAW_BLE_DEBUG not set in this shell", False,
              "unset it before building, or students will see BLE traces")

    # 3. Every copy of the shared classes must AGREE.
    #
    #    This used to assert PROX_THRESHOLD == 20, which was wrong twice over:
    #    the value is deliberately unsettled (it depends on a bench measurement
    #    of the raw ADC range, which differs between the Uno R4 at 5 V and the
    #    Giga at 3.3 V), and hardcoding an expected number here meant preflight
    #    failed for a decision that had been reversed on purpose.
    #
    #    What actually matters for a build is CONSISTENCY: the classes bundled
    #    into a student's generated sketch must match the reference firmware.
    #    They did not — materials/arduino_classes was outside sync_shared.py's
    #    reach and still carried the inverted CogLight polarity.
    import subprocess
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "firmware", "sync_shared.py"),
                        "--check"],
                       capture_output=True, text=True)
    check("shared Arduino classes are in sync", r.returncode == 0,
          "run: python firmware/sync_shared.py")
    if r.returncode != 0:
        for line in r.stdout.strip().splitlines()[:12]:
            print(f"          {line}")

    #    Report the tuning constants rather than asserting them, so a value
    #    that is meant to be reviewed is visible without failing the build.
    import re as _re
    ref = os.path.join(ROOT, "firmware", "shared", "EthologyRobot.h")
    if os.path.exists(ref):
        txt = open(ref).read()
        vals = {k: _re.search(k + r"\s*=\s*([0-9.]+)", txt)
                for k in ("PROX_THRESHOLD", "LIGHT_THRESHOLD",
                          "CRUISE_SPEED", "ARC_INNER_SPEED", "ARC_OUTER_SPEED")}
        print("\n  firmware tuning constants (informational, not asserted):")
        for k, m in vals.items():
            print(f"      {k:18s} {m.group(1) if m else '?'}")
        if vals["PROX_THRESHOLD"] and vals["PROX_THRESHOLD"].group(1) == "35":
            print("      NOTE: PROX_THRESHOLD 35 is the pre-bench-test value.")
            print("            Firmware and simulator now agree on 35, so this")
            print("            is no longer a divergence — but the underlying")
            print("            raw->cm mapping was derived on an Uno R4 (5 V)")
            print("            and is wrong on a Giga (3.3 V). Fix the mapping")
            print("            with a raw-ADC measurement on the board you are")
            print("            actually using, THEN choose the threshold.")

    # 4. Data files the spec wants. Missing ones are filtered out silently by
    #    the spec, so a typo there costs you a runtime failure instead.
    for rel in ("games/ethology/robot.json",
                "robots/ethology_v2.json",
                "robots/hardware_profiles.json",
                "materials/icons/hierarchy_builder.ico"):
        check(f"data: {rel}", os.path.exists(os.path.join(ROOT, rel)))

    import glob
    n_classes = len(glob.glob(os.path.join(ROOT, "materials", "arduino_classes", "*")))
    check("materials/arduino_classes non-empty", n_classes > 0, f"{n_classes} files")

    # 5. The BUILDING interpreter must carry PyInstaller AND the runtime deps.
    #    PyInstaller bundles what the interpreter running it can see, so a build
    #    under a different Python from this one silently omits packages and the
    #    app dies at startup. Run this preflight with the SAME interpreter you
    #    build with.
    print(f"\n  interpreter: {sys.executable}")
    print(f"  version    : {sys.version.split()[0]}")
    if sys.version_info[:2] > (3, 13):
        print("\n  *** pygame ships Windows wheels for Python 3.10-3.13 ONLY. ***")
        print("      On 3.14+ pip falls back to a source build and fails on")
        print("      distutils.msvccompiler. Run this and the build under an")
        print("      older interpreter:  py -3.12 packaging\\re_hierarchy_builder\\preflight.py")
    for mod, pipname in (("PyInstaller", "pyinstaller"),
                         ("pygame", "pygame"),
                         ("serial", "pyserial")):
        try:
            __import__(mod)
            check(f"{mod} available to THIS interpreter", True)
        except ImportError:
            check(f"{mod} available to THIS interpreter", False,
                  f"pip install {pipname}")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\n  Fix the failures above before running build_windows.bat.")
    else:
        print("\n  Ready. Run: packaging\\re_hierarchy_builder\\build_windows.bat")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
