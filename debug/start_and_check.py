# -*- coding: utf-8 -*-
"""启动 demo 并确认进程（结果写文件）。"""
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
subprocess.run(["cmd", "/c", "start", "", str(ROOT / "启动Demo.bat")],
               cwd=str(ROOT), shell=False)
time.sleep(7)
out = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
     "Where-Object {$_.CommandLine -like '*demo_main*'} | "
     "Select-Object ProcessId, CreationDate | ConvertTo-Json"],
    capture_output=True, text=True).stdout.strip()
Path(__file__).with_name("_procs.json").write_text(out or "[]", encoding="utf-8")
