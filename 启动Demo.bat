@echo off
rem ASCII-only content: %~dp0 expands to this bat's folder at runtime (Chinese path safe).
cd /d "%~dp0"
start "" "C:\Users\Stara\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" demo_main.py
