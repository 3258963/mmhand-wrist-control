@echo off
if not exist "%~dp0..\.venv\Scripts\pythonw.exe" (
    echo Please install the project environment first. See znsv_app/README.md.
    pause
    exit /b 1
)
start "" "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0main.py"
