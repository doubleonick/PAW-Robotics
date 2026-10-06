"""
games/ethology/arduino_export.py
----------------------------------
Writes the player's hypothesis as a self-contained Arduino project.

Arduino requires the sketch to live in a folder with the same name.
Two fixed folders are maintained:

  arduino_exports/
    current_hypothesis_A/
      current_hypothesis_A.ino
      CogServo.h
      EthologyRobot.h
      LDREthologyRobot.h
    current_hypothesis_B/
      current_hypothesis_B.ino
      CogServo.h
      EthologyRobot.h
      LDREthologyRobot.h

The .ino is overwritten each Launch Arduino press.
The .h files are written once and preserved if replaced with real ones.
"""

from __future__ import annotations
import os
import subprocess
import sys

GAME_DIR   = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(GAME_DIR, "arduino_exports")

# Source directory for the REAL, vetted Arduino class files (CogServo,
# EthologyRobot, etc.). The generator copies these into each sketch folder so
# the exported sketch ships with the verified hardware library — not stubs.
# Defaults to the project's materials/arduino_classes/; the packaging layer
# (frozen .exe) overrides this to the bundled resource location. Because the
# files are copied as plain files, they can be edited/improved in the field
# without touching the generator, as long as the called interface is preserved.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(GAME_DIR))


def _default_classes_dir() -> str:
    return os.path.join(_PROJECT_ROOT, "materials", "arduino_classes")


# Reassignable by a host (e.g. the frozen app points this at _internal/materials).
arduino_classes_provider = _default_classes_dir

# ── Stub headers ──────────────────────────────────────────────────────────────

_COGS_SERVO_H = """\
// CogServo.h — STUB
// Replace with the real CogServo library files when deploying to physical hardware.
// Required methods used by generated sketches:
//   void begin(int leftPin, int rightPin, bool initPWM = true)
//   void driveProportional(int left, int right, float duration)
//   void halt(float duration = 0)
//   float getLeftAngle()
//   float getRightAngle()
#pragma once
class CogServo {
public:
  void begin(int l, int r, bool p=true) {}
  void driveProportional(int l, int r, float d) {}
  void halt(float d=0) {}
  float getLeftAngle()  { return 90.0f; }
  float getRightAngle() { return 90.0f; }
};
"""

_ETHOLOGY_ROBOT_H = """\
// EthologyRobot.h — STUB
// Replace with the real EthologyRobot library files when deploying to physical hardware.
// Provides: escape_front(), escape_back(), avoid_object(), approach_object(),
//           cruise_straight(), cruise_arc(), begin()
//           front_contact_met(), rear_contact_met(), proximity_threshold_met(),
//           light_gradient_met() [always returns false in this class]
#pragma once
#include "CogServo.h"
class EthologyRobot {
public:
  EthologyRobot(CogServo& s) {}
  void begin() {}
  bool front_contact_met()       { return false; }
  bool rear_contact_met()        { return false; }
  bool proximity_threshold_met() { return false; }
  bool light_gradient_met()      { return false; }
  void escape_front()    {}
  void escape_back()     {}
  void avoid_object()    {}
  void approach_object() {}
  void approach_light()      {}
  void avoid_light()     {}
  void cruise_straight() {}
  void cruise_arc()      {}
};
"""

_LDR_ETHOLOGY_ROBOT_H = """\
// LDREthologyRobot.h — STUB
// Replace with the real LDREthologyRobot library files when deploying to physical hardware.
// Extends EthologyRobot with light sensor support:
//   light_gradient_met() returns true when LDR differential >= threshold
//   approach_light() / avoid_light() arc toward/away from brighter side
#pragma once
#include "CogServo.h"
class LDREthologyRobot {
public:
  LDREthologyRobot(CogServo& s) {}
  void begin() {}
  bool front_contact_met()       { return false; }
  bool rear_contact_met()        { return false; }
  bool proximity_threshold_met() { return false; }
  bool light_gradient_met()      { return false; }
  void escape_front()    {}
  void escape_back()     {}
  void avoid_object()    {}
  void approach_object() {}
  void approach_light()      {}
  void avoid_light()     {}
  void cruise_straight() {}
  void cruise_arc()      {}
};
"""

STUBS = {
    "CogServo.h":         _COGS_SERVO_H,
    "EthologyRobot.h":    _ETHOLOGY_ROBOT_H,
    # LDREthologyRobot.h is intentionally NOT emitted: the codegen supersedes it
    # (EthologyRobot now handles all sensors, light included), so the generated
    # sketch never #includes it. Emitting it just produced a dead, unused tab.
}


def _is_stub(path: str) -> bool:
    try:
        with open(path) as f:
            return "STUB" in f.read(120)
    except Exception:
        return False


def _ensure_headers(folder: str) -> None:
    """Copy the REAL, vetted Arduino class files into the sketch folder so the
    exported sketch ships with the verified hardware library — not stubs.

    Source is arduino_classes_provider() (the bundled materials/arduino_classes
    in a packaged build, or the project tree in dev). Files are copied only when
    missing or unchanged, so a real file the user has edited in the sketch
    folder is preserved. If the real classes can't be found (older layout), we
    fall back to writing the built-in stubs so the sketch still compiles."""
    import shutil
    src_dir = arduino_classes_provider()
    if os.path.isdir(src_dir):
        for fname in os.listdir(src_dir):
            if not (fname.endswith(".h") or fname.endswith(".cpp")):
                continue
            src = os.path.join(src_dir, fname)
            dst = os.path.join(folder, fname)
            try:
                # copy if missing; otherwise leave user-edited copies alone
                if not os.path.exists(dst):
                    shutil.copyfile(src, dst)
            except OSError:
                pass
        return
    # Fallback: no real classes available — write the built-in stubs.
    for fname, content in STUBS.items():
        path = os.path.join(folder, fname)
        if not os.path.exists(path) or _is_stub(path):
            with open(path, "w") as f:
                f.write(content)


# ── Export function ───────────────────────────────────────────────────────────

def export(sketch_source: str, robot_label: str) -> str:
    """
    Write sketch + headers to the fixed folder for this robot label.
    Returns path to the .ino file.
    """
    sketch_name = f"current_hypothesis_{robot_label}"
    folder      = os.path.join(EXPORT_DIR, sketch_name)
    os.makedirs(folder, exist_ok=True)

    _ensure_headers(folder)

    ino_path = os.path.join(folder, f"{sketch_name}.ino")
    with open(ino_path, "w") as f:
        f.write(sketch_source)

    return ino_path


def launch_ide(ino_path: str) -> bool:
    """
    Try to open the sketch in Arduino IDE.
    Returns True if a launcher was found, False if only explorer opened.
    """
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Arduino IDE\arduino-ide.exe",
            r"C:\Program Files (x86)\Arduino IDE\arduino-ide.exe",
            r"C:\Program Files\Arduino\arduino.exe",
            r"C:\Program Files (x86)\Arduino\arduino.exe",
            "arduino-ide",
            "arduino",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Arduino IDE.app/Contents/MacOS/arduino-ide",
            "/Applications/Arduino.app/Contents/MacOS/Arduino",
            "arduino-ide",
            "arduino",
        ]
    else:
        candidates = ["arduino-ide", "arduino"]

    for cmd in candidates:
        try:
            subprocess.Popen([cmd, ino_path])
            return True
        except (FileNotFoundError, OSError):
            continue

    # Fallback — open folder in file explorer
    folder = os.path.dirname(ino_path)
    try:
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass
    return False
