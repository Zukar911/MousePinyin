@echo off
rem ASCII-only content: %~dp0 expands to this bat's folder at runtime (Chinese path safe).
rem One-click dev environment setup: venv + deps + launcher scripts.
setlocal
cd /d "%~dp0"

echo ============================================
echo  MousePinyin - one-click environment setup
echo ============================================

rem ---- 1. locate python 3.13+ ----
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python not found in PATH. Install Python 3.13+ from python.org or:
  echo         winget install Python.Python.3.13
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/4] Found Python %PYVER%

rem ---- 2. create venv ----
if exist "venv\Scripts\python.exe" (
  echo [2/4] venv already exists, reuse it.
) else (
  echo [2/4] Creating venv ...
  python -m venv venv
  if errorlevel 1 (
    echo [ERROR] venv creation failed.
    pause
    exit /b 1
  )
)

rem ---- 3. install deps (Aliyun mirror, China-friendly) ----
echo [3/4] Installing dependencies (Aliyun mirror) ...
"venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --quiet
if errorlevel 1 (
  echo [ERROR] pip install failed. Check network or run again.
  pause
  exit /b 1
)

rem ---- 4. generate launcher scripts (venv-relative, portable) ----
echo [4/4] Writing launcher scripts ...
> "start-demo.bat" echo @echo off
>> "start-demo.bat" echo cd /d "%%~dp0"
>> "start-demo.bat" echo start "" "%%~dp0venv\Scripts\pythonw.exe" demo_main.py
> "start-demo-global.bat" echo @echo off
>> "start-demo-global.bat" echo cd /d "%%~dp0"
>> "start-demo-global.bat" echo start "" "%%~dp0venv\Scripts\pythonw.exe" demo_main.py --global
> "start-demo-debug.bat" echo @echo off
>> "start-demo-debug.bat" echo cd /d "%%~dp0"
>> "start-demo-debug.bat" echo "%%~dp0venv\Scripts\python.exe" demo_main.py --debug-panel

echo.
echo ============================================
echo  Setup complete!
echo   start-demo.bat          normal mode
echo   start-demo-global.bat   global-hook mode (Ctrl+Alt+M)
echo   start-demo-debug.bat    debug console mode
echo ============================================
choice /c YN /m "Launch demo now? [Y/N]"
if errorlevel 2 exit /b 0
start "" "%~dp0venv\Scripts\pythonw.exe" demo_main.py
exit /b 0
