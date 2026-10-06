@echo off
REM ===========================================================================
REM  clean_build.bat — remove every kind of stale state before a rebuild.
REM
REM  Run from anywhere; it resolves the project root itself:
REM      packaging\re_hierarchy_builder\clean_build.bat
REM
REM  Removes, in order of how often each actually causes trouble:
REM    1. _output\build  — PyInstaller's work dir. A failed build leaves a
REM       half-written analysis here that a later build can reuse.
REM    2. _output\dist   — the previous app. --noconfirm overwrites files but
REM       does NOT delete ones no longer produced, so a stale DLL or .pyd from
REM       an older attempt can survive and get loaded.
REM    3. PyInstaller's own cache (%LOCALAPPDATA%\pyinstaller) — caches
REM       processed binaries ACROSS projects and interpreters. This is the one
REM       that bites after you switch Python versions.
REM    4. __pycache__ / *.pyc in the source tree — stale bytecode can be
REM       analysed instead of the current source.
REM    5. build\ and dist\ INSIDE the repo — left by older builds, from before
REM       output moved to the external _output\ folder. Easy to mistake for the
REM       current app.
REM
REM  Touches no source and no installed packages. Safe to run any time.
REM ===========================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.."
set "ROOT=%CD%"
pushd ..
set "OUTBASE=%CD%\_output"
popd

echo.
echo === Cleaning RE Hierarchy Builder build state ===
echo   Source: %ROOT%
echo   Output: %OUTBASE%
echo.

REM --- 1 + 2: the external output folder --------------------------------------
if exist "%OUTBASE%" (
    echo [1/5] Removing %OUTBASE%
    rmdir /s /q "%OUTBASE%"
    if exist "%OUTBASE%" (
        echo       WARNING: could not fully remove it.
        echo       Close the app and any Explorer window showing that folder.
    )
) else (
    echo [1/5] %OUTBASE% — not present, nothing to do
)

REM --- 3: PyInstaller's cross-project cache ------------------------------------
if exist "%LOCALAPPDATA%\pyinstaller" (
    echo [2/5] Removing PyInstaller cache: %LOCALAPPDATA%\pyinstaller
    rmdir /s /q "%LOCALAPPDATA%\pyinstaller"
) else (
    echo [2/5] PyInstaller cache — not present
)

REM --- 4: stale bytecode in the source tree ------------------------------------
echo [3/5] Removing __pycache__ folders
for /d /r "%ROOT%" %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"

echo [4/5] Removing stray .pyc files
del /s /q "%ROOT%\*.pyc" >NUL 2>&1

REM --- 5: legacy in-tree build output ------------------------------------------
echo [5/5] Removing in-tree build\ and dist\ (legacy locations)
if exist "%ROOT%\build" rmdir /s /q "%ROOT%\build"
if exist "%ROOT%\dist"  rmdir /s /q "%ROOT%\dist"

echo.
echo === Clean complete ===
echo.
echo Next:
echo   py -3.12 packaging\re_hierarchy_builder\preflight.py
echo   packaging\re_hierarchy_builder\build_windows.bat
echo.
echo If preflight reports an interpreter you did not expect, that is the bug —
echo PyInstaller bundles only what the interpreter running it can see.
echo.
popd
popd
endlocal
