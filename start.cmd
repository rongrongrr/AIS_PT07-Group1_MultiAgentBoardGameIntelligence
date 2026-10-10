@echo off
rem TILES entry point for Windows (Command Prompt or PowerShell).
rem
rem   start.cmd               API + hot-reload web app (http://localhost:5173)
rem   start.cmd app           one process, built web app (http://localhost:8000)
rem   start.cmd docker        in a container (http://localhost:8000)
rem   start.cmd --help        every option
rem
rem This only finds Python 3.10+; run.py does the rest (macOS/Linux: start.sh).
setlocal
set "RUN=%~dp0run.py"
set "CHECK=import sys; sys.exit(sys.version_info < (3, 10))"

py -3 -c "%CHECK%" >nul 2>&1 && goto use_py
python -c "%CHECK%" >nul 2>&1 && goto use_python
python3 -c "%CHECK%" >nul 2>&1 && goto use_python3

echo TILES needs Python 3.10 or newer: https://www.python.org/downloads/ 1>&2
exit /b 1

:use_py
py -3 "%RUN%" %*
exit /b %errorlevel%

:use_python
python "%RUN%" %*
exit /b %errorlevel%

:use_python3
python3 "%RUN%" %*
exit /b %errorlevel%
