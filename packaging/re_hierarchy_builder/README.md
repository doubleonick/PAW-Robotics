# RE Hierarchy Builder — Standalone App Packaging

## For instructors: setting up the Robot Ethology lab

When you launch the application and choose **Instructor**, you'll reach a setup
page. Here is that workflow, for reference:

> Press the **Initialize Robot** button to launch the Arduino IDE with a sketch
> that has all of the scaffolding for the Robot Ethology lab. Connect your
> Arduino, select your board and port, and upload the sketch. Once your upload
> is done, return to that page and press **Continue**. You will then be taken to
> the Hierarchy Builder your students will use, and you will build the target
> hierarchy(ies) that you will be using in your lab. Make sure the target robot
> is on and running the sketch you uploaded, and, once your hierarchy is what
> you want, press **Send via BLE** in the Builder.

Students who launch the app and choose **Student** go straight to the Hierarchy
Builder.

---

## Packaging / build notes (for the developer)

This folder builds the **Robot Ethology Hierarchy Builder** as a standalone
desktop application — no Python install required on the target machine, no
PyBullet, just a double-clickable app.

It is the first of the classroom tools to be packaged (FW-008). The build is
**per-platform**: a Windows `.exe` must be built on Windows; a macOS `.app` on
a Mac. This README covers **Windows** (do this first). macOS instructions will
follow once the Windows build is verified.

---

## What's in this folder

| File | Purpose |
|------|---------|
| `re_hierarchy_builder_app.py` | The standalone entry point PyInstaller turns into the app. Wires writable output paths and launches the builder with no game shell. |
| `app_paths.py` | Path helper — resolves bundled resources and per-user writable locations, working both in dev and in the frozen build. |
| `re_hierarchy_builder.spec` | PyInstaller build recipe — declares what code and data files go into the app. |
| `build_windows.bat` | One-command Windows build script. |
| `README.md` | This file. |

---

## Windows build — step by step

### 1. Prerequisites

Install Python 3.10+ (the same Python you develop with is fine), then:

```
pip install pygame pyserial pyinstaller
```

### 2. Build

From the **project root** (the folder containing `games/`, `engine/`, etc.) in
a Command Prompt:

```
packaging\re_hierarchy_builder\build_windows.bat
```

The script cleans old builds and runs PyInstaller against the spec. It finishes
with:

```
dist\RE Hierarchy Builder\RE Hierarchy Builder.exe
```

### 3. Test

Double-click `dist\RE Hierarchy Builder\RE Hierarchy Builder.exe`, or run it
from the command line to see any error output:

```
"dist\RE Hierarchy Builder\RE Hierarchy Builder.exe"
```

You should get the Hierarchy Builder window with the left-side actions:
**Clear All**, **Launch Arduino**, **Send via BLE**. (No "Launch Experiment" —
that was the game action and is intentionally gone in the standalone app.)

### 4. Verify the real workflow (on hardware)

The packaging is only "done" once these work from inside the `.exe`:

- **Send via BLE** — pair the robot's Bluetooth module (HC-05/HC-06) in Windows
  first, so it gets a COM port; then the builder's BLE send should reach it.
- **Launch Arduino** — if the Arduino IDE is installed, the generated `.ino`
  opens in it; if not, the app falls back to just writing the `.ino` (see
  "Where files go" below) so nothing is lost.

---

## Where files go (runtime outputs)

The app writes generated sketches and metadata to a **per-user writable
folder**, not next to the `.exe` (the app folder is effectively read-only):

```
%LOCALAPPDATA%\PAW Hierarchy Builder\
    sketches\            generated .ino sketches (Generate Sketch)
    arduino_exports\     export folders used by Launch Arduino
    last_result.json     harmless run metadata
```

You can paste `%LOCALAPPDATA%\PAW Hierarchy Builder` into the Explorer address
bar to find them. This keeps the student-facing app clean — they interact with
the builder, not loose files.

---

## How it works (for future maintenance)

- **No PyBullet.** The hierarchy builder authors a hierarchy and generates an
  Arduino sketch; it never simulates, so the physics engine is excluded from
  the build entirely (see `excludes` in the spec). The classroom robots are
  physical — the sim isn't part of this tool.
- **Resource vs. writable paths** are separated in `app_paths.py`. Bundled
  read-only inputs (robot.json, hardware profiles, icon, BLE-fail script)
  resolve via `resource_path()`; runtime outputs go through `user_data_dir()`.
  This split is what makes the frozen app behave correctly — the #1 source of
  "works in dev, breaks packaged" bugs is writing into the read-only bundle.
- **Output redirection** happens in `re_hierarchy_builder_app.py`
  (`_configure_output_paths`): it overrides the builder's `sketches_dir_provider`
  / `robot_json_provider` hooks and `arduino_export.EXPORT_DIR`. The builder
  itself is unchanged in dev — these hooks default to the source-tree layout.

---

## Troubleshooting

**App opens then closes immediately** — run the `.exe` from a Command Prompt to
see the traceback. Most likely a missing data file: check the `datas` list in
the spec against what actually exists in your tree.

**"Failed to execute script"** — usually a missing hidden import. Add the
offending module to `hiddenimports` in the spec and rebuild.

**Fonts look wrong** — the app uses system fonts (Courier New / Helvetica) via
`SysFont`, falling back to a default if unavailable. No font files are bundled;
this is expected and harmless.

**BLE send fails** — confirm the robot's Bluetooth module is paired in Windows
and has a COM port (Device Manager → Ports). The app talks plain serial over
that COM port via pyserial; it does not do native BLE.

**Windows SmartScreen warning on first run** — an unsigned `.exe` triggers a
"Windows protected your PC" prompt (More info → Run anyway). Code-signing
removes this but requires a certificate; for classroom distribution from a
known source the warning is usually acceptable. Note for later.

---

## Status / next

- [x] Windows packaging kit (this folder)
- [ ] Build + verify `.exe` on a Windows machine (you)
- [ ] Confirm BLE send + Launch Arduino work from the packaged app (on hardware)
- [ ] macOS `.app` build (after Windows is verified)
- [ ] Then: package VV / BYOV (keeps its vector-math sim; see FW-008)


---

## Building it (dev14 refresh, 2026-08-06)

**A Windows `.exe` must be built on Windows** — PyInstaller does not
cross-compile. This repo cannot produce one from Linux, so the source here is
verified-ready and the build is one command on your machine.

### 1. Preflight (seconds)

From the repo root:

```
python packaging\re_hierarchy_builder\preflight.py
```

Every check must pass. A PyInstaller build takes minutes and fails cryptically;
this catches the known traps first.

### 2. Build

```
packaging\re_hierarchy_builder\build_windows.bat
```

Output lands in `dist/`.

### What preflight checks, and why each one matters

| Check | Why |
|---|---|
| Imports with **PyBullet excluded** | dev14 made PyBullet a hard dependency of all three GAMES. The builder must stay free of it: it is a UI, not a simulator, and bundling it would add a native dependency and ~100 MB to a classroom app. The spec excludes it; this proves nothing sneaks it back in. |
| **BLE traces quiet** | `[BLE-DEBUG]` prints are now gated behind `PAW_BLE_DEBUG`. Students should never see them; during BLE bring-up you still can. |
| Bundled **firmware `PROX_THRESHOLD == 20`** | The app ships the sketches the instructor uploads. dev14 changed this constant from 35/33/15 (three different values) to 20 everywhere. A stale bundled copy means the robot behaves differently from the simulator the lab was designed against. |
| Data files present | The spec filters missing entries silently, so a typo there becomes a runtime failure instead of a build failure. |

### dev14 changes that reach this app

- **`PROX_THRESHOLD` is now 20 cm** in the bundled firmware and
  `materials/arduino_classes`, down from 35. Avoidance triggers much later, and
  the robot will sometimes reach its bump sensors before avoiding —
  `escapeFrontCollision` handles that. This is a **visible behaviour change** in
  the classroom; worth mentioning to instructors.
- **`[BLE-DEBUG]` prints gated** behind `PAW_BLE_DEBUG=1`.
- **`robots/ethology_v2.json` is the chassis source of truth** — 155 mm bounding
  square. The builder tree previously carried a 169 mm figure in
  `robot_builder.CHASSIS`; corrected.

### Still deliberately excluded

`pybullet`, `pybullet_data`, `engine.simulation`,
`engine.adapters.pybullet_drive`, `numpy.f2py`, `tkinter`. The builder needs
none of them, and dev14 did not change that — verified by preflight.


---

## Troubleshooting: `ModuleNotFoundError` from the frozen app

Symptom — the `.exe` builds fine, then dies immediately:

```
File "engine\theme.py", line 4, in <module>
ModuleNotFoundError: No module named 'pygame'
```

**Cause: the build ran under a different Python from the one the project uses.**
PyInstaller bundles what the interpreter *running it* can see. If you develop
with `py -3.12` but `pyinstaller` on PATH belongs to some other install, every
package present only in 3.12 is silently left out — and the failure surfaces at
app startup, not at build time.

Fixed in `build_windows.bat`: it now pins one interpreter (the plain `python` on PATH by
default) and uses `%PY% -m PyInstaller`, so the building and target environments
cannot diverge. It also refuses to build unless that interpreter has PyInstaller,
pygame and pyserial.

To build with a different Python:

```
set PY=py -3.13
packaging\re_hierarchy_builder\build_windows.bat
```

or point `PY` at a venv's `python.exe`.

**Run preflight with the same interpreter you build with** — it prints
`sys.executable` so you can confirm they match:

```
python packaging\re_hierarchy_builder\preflight.py
```

`pygame` is also named explicitly in the spec's `hiddenimports` as a second line
of defence, so analysis cannot lose it even if it is only reached indirectly.


---

## Where to run the commands

Both scripts resolve the project root themselves, so the working directory does
not matter. The documented form is from the project root:

```
C:\PAW-build\PAW-Robotics-refactor> packaging\re_hierarchy_builder\build_windows.bat
```

**Which interpreter matters far more than which directory.** `preflight.py`
prints `sys.executable`; if that is not the Python you expect, stop and fix that
first.

## After failed builds — clean first

```
packaging\re_hierarchy_builder\clean_build.bat
python packaging\re_hierarchy_builder\preflight.py
packaging\re_hierarchy_builder\build_windows.bat
```

`clean_build.bat` touches no source and no installed packages. What it removes,
and why each matters:

| Removed | Why |
|---|---|
| `_output\build` | PyInstaller's work dir. A failed build leaves a half-written analysis a later build can reuse. |
| `_output\dist` | `--noconfirm` overwrites files but does **not** delete ones no longer produced, so a stale DLL or `.pyd` from an older attempt can survive and get loaded. |
| `%LOCALAPPDATA%\pyinstaller` | PyInstaller's cache of processed binaries, shared **across projects and interpreters**. This is the one that bites after switching Python versions — exactly the situation that caused the missing-pygame failure. |
| `__pycache__`, `*.pyc` | Stale bytecode can be analysed instead of current source. |
| in-tree `build\`, `dist\` | Legacy locations from before output moved to `_output\`. Easy to mistake for the current app. |

If it reports it could not fully remove `_output`, close the built app and any
Explorer window showing that folder — Windows holds locks on running binaries
and on directories open in a shell.

### What clean_build does NOT touch

Installed packages. If a dependency is broken rather than stale, reinstall it
into the interpreter you build with:

```
python -m pip install --force-reinstall pygame pyserial pyinstaller
```

Note `python -m pip`, not bare `pip` — bare `pip` may belong to a different
interpreter, which is the same class of mistake that produced the missing-pygame
failure in the first place.
