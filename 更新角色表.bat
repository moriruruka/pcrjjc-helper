@echo off
setlocal
cd /d "%~dp0"

rem One-click refresh of the character table, committed with the maintainer identity.
rem Interpreter lookup: repo .venv -> PCRJJC_PYTHON -> py -3 -> python

set "PYCMD="
if exist "%~dp0.venv\Scripts\python.exe" set "PYCMD=%~dp0.venv\Scripts\python.exe"
if not defined PYCMD if defined PCRJJC_PYTHON set "PYCMD=%PCRJJC_PYTHON%"
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD set "PYCMD=python"

echo [1/3] interpreter: %PYCMD%
"%PYCMD%" -c "import aiohttp, PIL" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Missing dependencies aiohttp / Pillow for this interpreter.
    echo Run once in the repo root:  "%PYCMD%" -m pip install -e .
    echo Or set PCRJJC_PYTHON to a python.exe that already has them.
    echo.
    pause
    exit /b 1
)

echo [2/3] refreshing characters.json and pushing...
"%PYCMD%" scripts\update_dataset.py --commit --push
if errorlevel 1 (
    echo.
    echo Update failed, see the output above.
    pause
    exit /b 1
)

echo.
echo [3/3] latest commit:
git log -1 --format="%%h %%an <%%ae>  %%s"
echo.
pause
