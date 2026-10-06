#!/usr/bin/env python3
"""
check_firmware.py — compile and LINK the Arduino sketches without an IDE,
a board, or the real Arduino libraries.

    py -3.12 tools/firmware_check/check_firmware.py
    py -3.12 tools/firmware_check/check_firmware.py --project ethology_ble_robot

WHY THIS EXISTS
---------------
CLAUDE.md carried "Nothing in firmware/ can be compiled in a sandbox" as a
standing limitation, and that is how a link-time error survived: a #define in
a .ino does not reach CogDisplay.cpp, which is a separate translation unit, so
the sketch declares real methods while the library compiles empty inline ones
and the build fails with

    undefined reference to `CogDisplay::setGuards(bool const*, int)'

A syntax check on individual files cannot see that. This builds the sketch as a
REAL multi-translation-unit program against the stubs in stubs/, which is the
arrangement that produces the error.

It also builds at every PAW_USE_DISPLAY / PAW_DISPLAY_DEV combination, because
those switches change which methods CogDisplay declares, and compiles CogLight
at both PAW_LIGHT_HIGH_IS_BRIGHT settings.

WHAT IT CANNOT CATCH
--------------------
Anything board-specific: timing, servo behaviour, real BLE, actual pin
behaviour. It proves the code BUILDS, never that a robot does the right thing.
firmware/README.md and the hardware checklist cover what needs a real robot.

STUBS ARE DELIBERATELY INCOMPLETE
---------------------------------
stubs/ declares only what this firmware uses. If a check fails with
"no member named X" or "no matching function", the stub is behind the real
Arduino API: ADD THE SIGNATURE TO THE STUB. Do not change the firmware to
avoid it. The firmware is what ships; the stub is scaffolding.

REQUIRES g++ on PATH. On Windows that usually means MinGW-w64 or WSL; if it is
missing this script says so and exits 0 rather than failing a build.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FIRMWARE = os.path.join(ROOT, "firmware")
STUBS = os.path.join(HERE, "stubs")

# Projects this harness can currently build, and the display settings to try.
#
# potential_field_* are NOT here yet: they use Arduino APIs the stubs do not
# declare (the PI macro, String(float, decimals), String + int). Those are stub
# gaps, not firmware faults. Add the signatures to stubs/Arduino.h and move the
# projects into this list.
PROJECTS = {
    "ethology_ble_robot":  [(0, 0), (1, 0), (1, 1)],
    "ethology_standalone": [(0, 0)],
}

INO_MAIN = """void setup();
void loop();
int main() { setup(); loop(); return 0; }
"""


def have_gxx() -> bool:
    return shutil.which("g++") is not None


def build(project: str, use_display: int, display_dev: int) -> tuple[bool, str]:
    """Build one project at one display setting. Returns (ok, compiler output)."""
    src = os.path.join(FIRMWARE, project)
    work = tempfile.mkdtemp(prefix=f"pawfw_{project}_")
    try:
        for f in os.listdir(STUBS):
            shutil.copy2(os.path.join(STUBS, f), work)
        for f in os.listdir(src):
            if f.endswith((".h", ".cpp")):
                shutil.copy2(os.path.join(src, f), work)

        # The .ino is the translation unit that matters most — it is where the
        # build switches are read and where CogDisplay's real methods are
        # called. Compile it as its own TU, exactly as the IDE does.
        shutil.copy2(os.path.join(src, f"{project}.ino"),
                     os.path.join(work, "sketch.cpp"))
        with open(os.path.join(work, "inomain.cpp"), "w") as fh:
            fh.write(INO_MAIN)

        srcs = ["sketch.cpp", "inomain.cpp"]
        srcs += [f for f in sorted(os.listdir(work))
                 if f.endswith(".cpp") and f not in ("sketch.cpp", "inomain.cpp")]

        cmd = ["g++", "-std=gnu++17", "-Wall", "-I.",
               f"-DPAW_USE_DISPLAY={use_display}",
               f"-DPAW_DISPLAY_DEV={display_dev}"]
        cmd += srcs + ["-o", os.devnull]

        p = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
        return p.returncode == 0, p.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)


def check_light_polarity() -> tuple[bool, str]:
    """CogLight must compile both ways round, or one sensor type is unbuildable."""
    src = os.path.join(FIRMWARE, "ethology_ble_robot")
    work = tempfile.mkdtemp(prefix="pawfw_light_")
    try:
        for f in os.listdir(STUBS):
            shutil.copy2(os.path.join(STUBS, f), work)
        for f in os.listdir(src):
            if f.endswith((".h", ".cpp")):
                shutil.copy2(os.path.join(src, f), work)
        for value in (0, 1):
            p = subprocess.run(
                ["g++", "-std=gnu++17", "-Wall", "-I.",
                 f"-DPAW_LIGHT_HIGH_IS_BRIGHT={value}",
                 "-c", "CogLight.cpp", "-o", os.devnull],
                cwd=work, capture_output=True, text=True)
            if p.returncode != 0:
                return False, f"PAW_LIGHT_HIGH_IS_BRIGHT={value}\n{p.stderr}"
        return True, ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--project", help="build only this project")
    args = ap.parse_args()

    if not have_gxx():
        print("g++ not found on PATH — skipping the firmware link check.")
        print("Install MinGW-w64 (Windows) or build-essential (Linux/WSL) to enable it.")
        return 0

    targets = PROJECTS
    if args.project:
        if args.project not in PROJECTS:
            print(f"ERROR: unknown project '{args.project}'. "
                  f"Known: {', '.join(sorted(PROJECTS))}")
            return 1
        targets = {args.project: PROJECTS[args.project]}

    failures = 0
    for project, settings in sorted(targets.items()):
        for use_display, display_dev in settings:
            label = f"{project}  USE_DISPLAY={use_display} DISPLAY_DEV={display_dev}"
            ok, err = build(project, use_display, display_dev)
            if ok:
                print(f"  OK    {label}")
            else:
                failures += 1
                print(f"  FAIL  {label}")
                for line in err.splitlines():
                    if "error" in line or "undefined" in line:
                        print(f"          {line}")

    ok, err = check_light_polarity()
    if ok:
        print("  OK    CogLight compiles at both PAW_LIGHT_HIGH_IS_BRIGHT settings")
    else:
        failures += 1
        print("  FAIL  CogLight polarity switch")
        print(err)

    print()
    if failures:
        print(f"{failures} check(s) failed.")
        print("If the error is a missing Arduino API, extend tools/firmware_check/"
              "stubs/ rather than changing the firmware.")
        return 1
    print("All firmware checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
