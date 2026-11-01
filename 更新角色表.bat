@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 一键更新角色表：抓取 /units、合并中文名、用维护者身份提交并推送。
rem 解释器查找顺序：仓库内 .venv → 环境变量 PCRJJC_PYTHON → py -3 → python

set "PYCMD="
if exist "%~dp0.venv\Scripts\python.exe" set "PYCMD=%~dp0.venv\Scripts\python.exe"
if not defined PYCMD if defined PCRJJC_PYTHON set "PYCMD=%PCRJJC_PYTHON%"
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD set "PYCMD=python"

echo [1/3] 检查解释器：%PYCMD%
%PYCMD% -c "import aiohttp, PIL" >nul 2>nul
if errorlevel 1 (
    echo.
    echo 当前解释器缺少依赖 aiohttp / Pillow。
    echo 请在仓库根目录执行一次：%PYCMD% -m pip install -e .
    echo 或设置环境变量 PCRJJC_PYTHON 指向已装好依赖的 python.exe。
    echo.
    pause
    exit /b 1
)

echo [2/3] 更新角色表（抓取 + 合并中文名）……
%PYCMD% scripts\update_dataset.py --commit --push
if errorlevel 1 (
    echo.
    echo 更新失败，请查看上面的输出。
    pause
    exit /b 1
)

echo.
echo [3/3] 最近一次提交：
git log -1 --format="%%h %%an <%%ae>  %%s"
echo.
pause
