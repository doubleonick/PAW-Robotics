"""
packaging/re_hierarchy_builder/app_paths.py
-------------------------------------------
Path resolution that works BOTH in development and inside a frozen PyInstaller
executable. This is the single linchpin of the packaging: nearly every
"works in dev, breaks in the .exe" bug is a path that assumed the source-tree
layout and didn't account for the frozen bundle.

Two distinct kinds of path:

  • RESOURCE paths (read-only inputs bundled INTO the app): robot.json, the
    icon, scripts/, robots/ hardware profiles, etc. In dev these live in the
    source tree; when frozen, PyInstaller unpacks them to a temporary dir
    exposed as sys._MEIPASS. `resource_path()` resolves either case.

  • WRITABLE paths (runtime OUTPUTS the app produces): generated .ino sketches,
    the result file, theme settings.json. These must NOT be written next to the
    frozen exe (that location is effectively read-only / temporary). They go to
    a per-user writable app-data directory. `user_data_dir()` resolves it
    per-platform; `writable_path()` joins into it (creating dirs as needed).
"""
from __future__ import annotations

import os
import sys


# ── frozen detection ─────────────────────────────────────────────────────────
def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) frozen build."""
    return getattr(sys, "frozen", False)


# ── resource (read-only, bundled) paths ──────────────────────────────────────
def _resource_root() -> str:
    """Root under which bundled resources live.

    Frozen: PyInstaller extracts data files to sys._MEIPASS.
    Dev:    the project root (two levels up from this file:
            packaging/re_hierarchy_builder/ -> project root).
    """
    if is_frozen():
        # PyInstaller sets _MEIPASS to the unpack dir; fall back to exe dir.
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled, read-only resource.

    Example: resource_path("games", "ethology", "robot.json")
    """
    return os.path.join(_resource_root(), *parts)


# ── writable (per-user output) paths ─────────────────────────────────────────
_APP_DIR_NAME = "PAW Hierarchy Builder"


def user_data_dir() -> str:
    """Per-user writable directory for this app's runtime outputs.

    Windows: %LOCALAPPDATA%\\PAW Hierarchy Builder
    macOS:   ~/Library/Application Support/PAW Hierarchy Builder
    Linux:   ~/.local/share/PAW Hierarchy Builder  (XDG_DATA_HOME if set)

    The directory is created on first use.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or \
            os.path.expanduser("~/.local/share")
    d = os.path.join(base, _APP_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def writable_path(*parts: str) -> str:
    """Absolute path to a writable output location under the user data dir,
    creating intermediate directories. Example:
        writable_path("sketches", "current_hypothesis_A.ino")
    """
    full = os.path.join(user_data_dir(), *parts)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full
