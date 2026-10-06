# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the RE Hierarchy Builder standalone app.

Build (from the PROJECT ROOT, on the target platform):
    pyinstaller packaging/re_hierarchy_builder/re_hierarchy_builder.spec

Produces:
    dist/RE Hierarchy Builder/RE Hierarchy Builder(.exe)      [onedir build]

We use a ONEDIR build (a folder with the exe + dependencies) rather than
onefile because: it starts faster, it's easier to debug missing-data issues,
and an installer (Inno Setup / a zip) can wrap the folder. Switch to onefile
later if you prefer a single loose .exe.

Data files: the builder reads robot.json, the hardware profiles in robots/,
the window icon, and the BLE-failure script. These are declared in `datas`
so PyInstaller copies them into the bundle, preserving relative layout so the
resource_path() helper finds them.
"""
import os

# The spec file's own directory: packaging/re_hierarchy_builder/
SPECDIR = os.path.dirname(os.path.abspath(SPEC))           # noqa: F821
ROOT = os.path.normpath(os.path.join(SPECDIR, "..", ".."))  # project root

ENTRY = os.path.join(SPECDIR, "re_hierarchy_builder_app.py")
ICON_PNG = os.path.join(ROOT, "materials", "icons", "hierarchy_builder.png")
ICON_ICO = os.path.join(ROOT, "materials", "icons", "hierarchy_builder.ico")


def _data(src_rel, dest_rel):
    """(absolute source, destination dir inside bundle) — only if it exists."""
    src = os.path.join(ROOT, src_rel)
    return (src, dest_rel) if os.path.exists(src) else None


# Read-only data files to bundle, preserving their relative paths so
# resource_path("games","ethology","robot.json") etc. resolve inside the bundle.
_candidate_datas = [
    _data("games/ethology/robot.json",                 "games/ethology"),
    _data("robots/hardware_profiles.json",             "robots"),
    _data("robots/ethology_v2.json",                   "robots"),
    _data("materials/icons/hierarchy_builder.png",     "materials/icons"),
    _data("materials/icons/hierarchy_builder.ico",     "materials/icons"),
    _data("scripts/paw_bot/ble_connect_failed.txt",    "scripts/paw_bot"),
    _data("games/ethology/scripts/paw_bot/ble_connect_failed.txt",
          "games/ethology/scripts/paw_bot"),
    _data("settings.json",                             "."),
]
datas = [d for d in _candidate_datas if d is not None]

# Whole directories to bundle:
#  - materials/arduino_classes: vetted classes copied into each GENERATED sketch
#    (the Launch Arduino path).
#  - firmware/: BOTH Arduino sketches the instructor receives —
#       ethology_ble_robot/   (the live BLE robot firmware, launched by
#                              "Initialize Robot")
#       ethology_standalone/  (the non-BLE teach-the-code reference)
#    Bundled from the single canonical firmware/ source so dist/ is complete and
#    the instructor never needs the parent project.
import glob as _glob
for _src in _glob.glob(os.path.join(ROOT, "materials", "arduino_classes", "*")):
    datas.append((_src, "materials/arduino_classes"))
for _root_dir, _dirs, _files in os.walk(os.path.join(ROOT, "firmware")):
    for _f in _files:
        _abs = os.path.join(_root_dir, _f)
        _rel = os.path.relpath(os.path.dirname(_abs), ROOT)
        datas.append((_abs, _rel))

# Hidden imports: modules imported dynamically (inside functions / by string)
# that PyInstaller's static analysis can miss. The builder imports these lazily.
hiddenimports = [
    # Runtime deps named explicitly. PyInstaller usually finds pygame by
    # following `import pygame` in engine/theme.py, but that only works if the
    # interpreter running PyInstaller HAS pygame — and a build under the wrong
    # interpreter produced a frozen app that died with
    # "ModuleNotFoundError: No module named 'pygame'" at engine/theme.py line 4.
    # build_windows.bat now pins the interpreter; this is the second line of
    # defence, and it makes the dependency visible rather than implicit.
    "pygame",
    "engine.theme",
    "engine.bluetooth.robot_bt_client",
    "games.ethology.codegen",
    "games.ethology.arduino_export",
    "intro_screens",
    "app_paths",
    "serial",            # pyserial — the BLE transport
    "serial.tools",
    "serial.tools.list_ports",
]

# Exclude the heavy/unneeded subsystems so they never get pulled in: PyBullet
# and the RE observation-sim modules have no place in this build.
excludes = [
    "pybullet",
    "pybullet_data",
    "engine.simulation",
    "engine.adapters.pybullet_drive",
    "numpy.f2py",
    "tkinter",
]


a = Analysis(                                              # noqa: F821
    [ENTRY],
    pathex=[ROOT, SPECDIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)                                          # noqa: F821

exe = EXE(                                                 # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RE Hierarchy Builder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # GUI app — no console window
    icon=ICON_ICO if os.path.exists(ICON_ICO) else None,
)

coll = COLLECT(                                            # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RE Hierarchy Builder",
)
