@echo off
rem ASCII-only content: %~dp0 expands to this bat's folder at runtime (Chinese path safe).
rem One-click upload: stage all changes, commit, push to GitHub (Zukar911/MousePinyin).
rem Usage: double-click (asks for a message)  |  or run:  push.bat "commit message"
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  set /p MSG=Commit message (what did you change):
) else (
  set "MSG=%~1"
)
if "%MSG%"=="" set "MSG=update %date% %time:~0,5%"

echo.
echo [1/3] Staging all changes ...
git add -A

echo [2/3] Committing "%MSG%" ...
git commit -m "%MSG%"
if errorlevel 1 (
  echo [i] Nothing new to commit - will still try push.
)

echo [3/3] Pushing to github.com/Zukar911/MousePinyin ...
git push
if errorlevel 1 (
  echo.
  echo [ERROR] Push failed. Usually one of:
  echo   - network hiccup (GitHub access from CN is flaky) - just run again
  echo   - credential expired - run: gh auth login
  pause
  exit /b 1
)

echo.
echo ============================================
echo  Upload complete: github.com/Zukar911/MousePinyin
echo ============================================
timeout /t 3 >nul
exit /b 0
