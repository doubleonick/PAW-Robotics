"""
packaging/re_hierarchy_builder/re_hierarchy_builder_app.py
----------------------------------------------------------
Standalone entry point for the packaged RE Hierarchy Builder (Windows .exe /
macOS .app). This is the file PyInstaller turns into the executable.

Responsibilities:
  • Put the project root on sys.path (works frozen or in dev).
  • Redirect the builder's OUTPUT paths (generated sketches) to a per-user
    writable app-data folder — the frozen app's own dir is read-only.
  • Point robot.json at the bundled resource.
  • Make the theme's settings.json live in the writable dir too (so theme
    persistence doesn't try to write into the read-only bundle).
  • Launch the builder in pure standalone mode (no game shell, no
    "Launch Experiment" hypothesis submission — that button is a game action
    and is suppressed here).
"""
from __future__ import annotations

import os
import sys

# Windows/bleak fix: some dependency may indirectly import a pywin32 module
# (pythoncom), whose side effect is to set this process's COM threading model to
# STA — which makes bleak's WinRT BLE backend fail ("Thread is configured for
# Windows GUI but callbacks are not working"). Setting coinit_flags = 0 (MTA)
# BEFORE those imports prevents the STA initialisation. Harmless on non-Windows.
sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED (MTA)

# Make sibling helper importable whether frozen or run from source.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from app_paths import resource_path, writable_path, user_data_dir, is_frozen

# Project root onto sys.path so `engine` / `games` import.
_ROOT = resource_path()  # frozen: _MEIPASS; dev: project root
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _seed_theme_settings() -> None:
    """The theme reads/writes settings.json next to the engine package, which is
    read-only when frozen — its writes fail silently and it falls back to the
    'phosphor' default, which is fine. We just make sure a default theme is
    applied. (If a future theme refactor adds a settings-path hook, redirect it
    here to the writable dir so theme choice can persist.)"""
    # nothing required for a working build; theme degrades gracefully when
    # frozen. Kept as a named step for clarity / future extension.
    return


def _configure_output_paths() -> None:
    """Send generated sketches to the writable app-data dir and read robot.json
    from the bundled resource, by overriding the builder's path providers.
    Also redirect arduino_export's EXPORT_DIR (used by the Launch Arduino path)
    to the writable location, since the frozen bundle dir is read-only."""
    import games.ethology.hierarchy_builder as hb
    import games.ethology.arduino_export as ae

    sketches = os.path.join(user_data_dir(), "sketches")
    os.makedirs(sketches, exist_ok=True)
    hb.sketches_dir_provider = lambda: sketches
    hb.robot_json_provider = lambda: resource_path(
        "games", "ethology", "robot.json")

    # arduino_export.export() reads EXPORT_DIR at call time; point it writable.
    ae.EXPORT_DIR = os.path.join(user_data_dir(), "arduino_exports")
    os.makedirs(ae.EXPORT_DIR, exist_ok=True)

    # Point the vetted-class source at the bundled materials/arduino_classes so
    # generated sketches ship with the real library (copied per sketch).
    ae.arduino_classes_provider = lambda: resource_path(
        "materials", "arduino_classes")


def main() -> None:
    _seed_theme_settings()
    import engine.theme as T
    # Apply the saved theme if available, else the default.
    try:
        T.apply(T.load_saved_theme())
    except Exception:
        T.apply("phosphor")

    import pygame
    pygame.init()

    # Window icon from bundled resources.
    icon = resource_path("materials", "icons", "hierarchy_builder.png")
    if os.path.exists(icon):
        try:
            pygame.display.set_icon(pygame.image.load(icon))
        except Exception:
            pass

    _configure_output_paths()

    import pygame
    # Size the window the same way the builder does, so all screens match.
    info = pygame.display.Info()
    taskbar = {"win32": 48, "darwin": 50}.get(__import__("sys").platform, 52)
    ww = max(820, info.current_w - 16)
    wh = max(560, info.current_h - taskbar - 16)
    screen = pygame.display.set_mode((ww, wh))
    pygame.display.set_caption("Robot Ethology")

    # ── Screen 1: role selection ──
    from intro_screens import role_select, instructor_setup
    role = role_select(screen)
    if role == "quit":
        pygame.quit()
        return

    # ── Screen 2 (instructors only): setup / Initialize Robot ──
    if role == "instructor":
        def _initialize_robot():
            """Launch the bundled BLE scaffolding sketch in the Arduino IDE,
            falling back to opening its folder if no IDE is found."""
            from games.ethology.arduino_export import launch_ide
            ino = resource_path("firmware", "ethology_ble_robot",
                                "ethology_ble_robot.ino")
            if not os.path.exists(ino):
                return "Firmware sketch not found in this build."
            ok = launch_ide(ino)
            return ("Opened firmware in Arduino IDE \u2014 connect your board, "
                    "select board/port, and upload."
                    if ok else
                    "Arduino IDE not found \u2014 the firmware folder was opened "
                    "instead; open ethology_ble_robot.ino manually.")

        if instructor_setup(screen, _initialize_robot) == "quit":
            pygame.quit()
            return

    # ── Screen 3: the Hierarchy Builder (both roles land here) ──
    from games.ethology.hierarchy_builder import HierarchyBuilder

    # Classroom mode: shows the HARDWARE actions (Launch Arduino, Send via BLE)
    # but NOT the in-game "Launch Experiment". The result_path is a harmless
    # metadata file in the writable user-data dir.
    result_path = writable_path("last_result.json")
    HierarchyBuilder(robot_label="", result_path=result_path,
                     classroom_mode=True).run()


if __name__ == "__main__":
    main()
