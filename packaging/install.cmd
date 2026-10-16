# CBZ 阅读器 —— 安装引导（纯 ASCII，避免批处理编码问题）
@echo off
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo.
  echo Install failed. Press any key to exit.
  pause >nul
)
endlocal
