@echo off
rem ASCII-only content: %~dp0 expands to this bat's folder at runtime (Chinese path safe).
rem Global-hook mode (P4): MousePinyin.exe --global
cd /d "%~dp0"
start "" "%~dp0MousePinyin.exe" --global
