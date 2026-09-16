@echo off
REM ============================================================
REM  push.bat —— 一键把改动提交并推送到 GitHub
REM ============================================================
REM  用法：
REM    push.bat                    用默认提交信息
REM    push.bat "你的提交说明"      自定义提交信息
REM
REM  凭据：走 Windows 凭据管理器（首次会弹 GitHub 登录窗口）。
REM  本脚本不会把 token 写进任何配置文件。
REM ============================================================
setlocal

cd /d "%~dp0"

set "MSG=%~1"
if "%MSG%"=="" set "MSG=chore: update"

echo [1/4] 检查是否在 git 仓库中...
git rev-parse --git-dir >nul 2>nul
if errorlevel 1 (
    echo    错误：当前目录不是 git 仓库。
    pause
    exit /b 1
)

echo [2/4] 暂存改动...
git add -A
if errorlevel 1 (
    echo    错误：git add 失败。
    pause
    exit /b 1
)

echo [3/4] 提交...
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MSG%"
    if errorlevel 1 (
        echo    错误：git commit 失败。
        pause
        exit /b 1
    )
) else (
    echo    没有需要提交的改动。
)

echo [4/4] 推送到 origin/main...
git push origin main
if errorlevel 1 (
    echo.
    echo    推送失败。常见原因：
    echo      - 网络 / 代理问题（SSL handshake failed）
    echo      - 凭据过期：删除 Windows 凭据管理器里的 git:https://github.com 后重试
    echo      - 远端有新提交：先 git pull --rebase origin main
    pause
    exit /b 1
)

echo.
echo 完成。
pause
