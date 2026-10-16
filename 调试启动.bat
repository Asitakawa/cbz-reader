@echo off
rem ---- CBZ Reader launcher (with console, for troubleshooting) ----
setlocal
set "PY=C:\Users\Arelq_\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\..\..\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0main.py"
echo.
echo exit code: %ERRORLEVEL%
pause
endlocal
