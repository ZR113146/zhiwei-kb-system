@echo off
setlocal
set "PYTHON=C:\Users\zhaor\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON%" set "PYTHON=py -3"
cd /d "%~dp0kb_core"
rd /s /q __pycache__ 2>nul
echo KB Search Server - fusion ranking
echo.
start http://localhost:8765
%PYTHON% server.py
pause
