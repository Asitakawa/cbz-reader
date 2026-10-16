@echo off
rem ---- CBZ Reader launcher (no console window) ----
setlocal
set "PYW=C:\Users\Arelq_\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0..\..\..\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0main.py"
endlocal
