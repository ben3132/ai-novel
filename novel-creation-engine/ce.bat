@echo off
rem ce.bat —— Windows 便捷入口。用法同 ce.py。
rem 解释器按顺序尝试：CE_PYTHON 环境变量 -> PATH 上的 python -> py 启动器。
setlocal
set "PY=%CE_PYTHON%"
if not defined PY set "PY=python"
where "%PY%" >nul 2>nul
if errorlevel 1 set "PY=py"
"%PY%" "%~dp0ce.py" %*
