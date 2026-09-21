@echo off
title PEPPERSTONE:XAUUSD Trading Terminal
cd /d "%~dp0"
echo ===================================================
echo   PEPPERSTONE:XAUUSD ZONE-TO-ZONE TRADING TERMINAL
echo ===================================================
echo Starting backend server on http://127.0.0.1:8080...
echo Launching terminal in your browser...
start "" "http://127.0.0.1:8080"
python server.py
pause
