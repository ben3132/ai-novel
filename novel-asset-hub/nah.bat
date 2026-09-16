@echo off
REM ============================================================
REM  novel-asset-hub 启动器（Windows）
REM  用法：  nah.bat --ws 我的小说 scan "..\processed\raw\ep_090.md"
REM  解释器按顺序尝试：NAH_PYTHON 环境变量 -> PATH 上的 python -> py 启动器。
REM ============================================================
setlocal
set "HERE=%~dp0"
set "PY=%NAH_PYTHON%"
if not defined PY set "PY=python"
where "%PY%" >nul 2>nul
if errorlevel 1 set "PY=py"
"%PY%" "%HERE%nah.py" %*
endlocal
