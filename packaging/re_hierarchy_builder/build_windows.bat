@echo off
REM ===========================================================================
REM  build_windows.bat — build the RE Hierarchy Builder .exe (Windows)
REM
REM  Run this from the PROJECT ROOT in a Command Prompt:
REM      packaging\re_hierarchy_builder\build_windows.bat
REM
REM  Requirements (installed into the Python you'll build with):
REM      pip install pygame pyserial pyinstaller
REM
REM  Build output goes OUTSIDE the source tree (to a sibling _output\ folder) so
REM  dist\ and build\ never clutter or get confused with the project source.
REM  Finished app:
REM      ..\_output\dist\RE Hierarchy Builder\RE Hierarchy Builder.exe
REM ===========================================================================

setlocal

REM --- Resolve project root (this script lives in packaging\re_hierarchy_builder\) ---
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.."
set "ROOT=%CD%"

REM --- External output location: a sibling _output\ folder next to the project ---
REM  e.g. project at C:\PAW-build\PAW-Robotics-refactor  ->  C:\PAW-build\_output
pushd ..
set "OUTBASE=%CD%\_output"
popd
set "DISTPATH=%OUTBASE%\dist"
set "WORKPATH=%OUTBASE%\build"

echo.
echo === Building RE Hierarchy Builder ===
echo   Source: %ROOT%
echo   Output: %DISTPATH%\RE Hierarchy Builder\
echo.

REM --- Sanity: confirm the spec exists ---
if not exist "packaging\re_hierarchy_builder\re_hierarchy_builder.spec" (
    echo ERROR: spec file not found. Run this from the project root.
    popd & exit /b 1
)

REM --- Pick ONE interpreter and use it for everything ------------------------
REM  PyInstaller bundles what the interpreter RUNNING IT can see. If the build
REM  runs under a different Python from the one the project is developed with,
REM  packages installed only in the project's Python are silently left out and
REM  the app dies at startup with ModuleNotFoundError.
REM
REM  That is exactly what bare `python` + bare `pyinstaller` caused here:
REM  pygame was missing from the frozen app.
REM
REM  Override with:  set PY=py -3.13   (or a venv's python.exe)
REM  AUTO-DETECT an interpreter that actually has the dependencies.
REM
REM  Hardcoding either `python` or a version is wrong on a machine with
REM  several Pythons installed, and both mistakes have now happened here:
REM  a build under the wrong Python produced an app that died with a missing
REM  pygame, and `python` on one machine turned out to be 3.14 -- for which
REM  pygame ships no Windows wheel at all (cp310-cp313 only), so even
REM  installing it fails.
REM
REM  So: try candidates in order and take the first that can already import
REM  pygame AND PyInstaller. Override with:  set PY=py -3.12
if not defined PY call :probe "python"
if not defined PY call :probe "py -3.13"
if not defined PY call :probe "py -3.12"
if not defined PY call :probe "py -3.11"

if not defined PY (
    echo ERROR: no Python on this machine has both pygame and PyInstaller.
    echo.
    echo   Tried: python, py -3.13, py -3.12, py -3.11
    echo.
    echo   pygame ships Windows wheels for Python 3.10-3.13 only. If your
    echo   default `python` is 3.14 or newer, pip will try to BUILD pygame
    echo   from source and fail. Use an older interpreter:
    echo.
    echo       py -3.12 -m pip install -r requirements.txt
    echo       set PY=py -3.12
    echo       packaging\re_hierarchy_builder\build_windows.bat
    echo.
    popd ^& exit /b 1
)
echo   Interpreter: %PY%

%PY% -c "import sys; print('   ->', sys.executable)"
if errorlevel 1 (
    echo ERROR: interpreter "%PY%" not found. Set PY to one that exists.
    popd & exit /b 1
)

REM --- The BUILDING interpreter must have both PyInstaller and the app deps ---
%PY% -c "import PyInstaller" 2>NUL
if errorlevel 1 (
    echo ERROR: PyInstaller not installed for %PY%.
    echo        Run:  %PY% -m pip install pyinstaller
    popd & exit /b 1
)
%PY% -c "import pygame" 2>NUL
if errorlevel 1 (
    echo ERROR: pygame not installed for %PY% — it would be missing from the app.
    echo        Run:  %PY% -m pip install pygame
    popd & exit /b 1
)
%PY% -c "import serial" 2>NUL
if errorlevel 1 (
    echo ERROR: pyserial not installed for %PY% — BLE transport would be missing.
    echo        Run:  %PY% -m pip install pyserial
    popd & exit /b 1
)

REM --- Build to the EXTERNAL output folder (keeps source tree clean) ---
%PY% -m PyInstaller --clean --noconfirm ^
    --distpath "%DISTPATH%" ^
    --workpath "%WORKPATH%" ^
    packaging\re_hierarchy_builder\re_hierarchy_builder.spec

if errorlevel 1 (
    echo.
    echo === BUILD FAILED - see messages above ===
    popd & exit /b 1
)

echo.
echo === BUILD COMPLETE ===
echo   App: "%DISTPATH%\RE Hierarchy Builder\RE Hierarchy Builder.exe"
echo.

popd
endlocal

goto :eof

REM ── :probe ────────────────────────────────────────────────────────────────
REM  Set PY to %1 if that interpreter can already import pygame and
REM  PyInstaller. Written as a CALL rather than a for-loop because a variable
REM  set inside a parenthesised block is not visible until the block ends,
REM  which would make the loop always pick the last candidate.
:probe
%~1 -c "import pygame, PyInstaller" >NUL 2>&1
if not errorlevel 1 (
    set "PY=%~1"
    echo   Using interpreter: %~1
)
exit /b 0
