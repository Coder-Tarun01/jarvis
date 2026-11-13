@echo off
title JARVIS desktop bridge
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app-bridge.ps1"
rem Only hold the window open when something actually went wrong; a refused
rem second instance exits 0 and should close instead of leaving a dead window.
if not "%ERRORLEVEL%"=="0" (
    echo.
    echo The bridge stopped with exit code %ERRORLEVEL%. Press any key to close.
    pause >nul
)
