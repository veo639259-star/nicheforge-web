@echo off
REM ============================================================
REM  NicheForge - Windows launcher
REM  Double-click this file to install deps and start the server.
REM ============================================================
cd /d "%~dp0"

echo Installing dependencies (this may take a moment)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements. Make sure Python 3.10+ is installed.
    pause
    exit /b 1
)

REM Load the master password automatically if .master-password exists
REM (created by tools\migrate_fb_tokens.py). No password typing needed.
if not defined NICHEFORGE_PASSWORD (
    if exist ".master-password" (
        set /p NICHEFORGE_PASSWORD=<".master-password"
    )
)

echo Opening NicheForge in your browser...
start "" "http://127.0.0.1:5057/"

echo Starting NicheForge server...
python app.py

REM Keep the window open if the server crashes, so the error is visible.
pause
