"""debug/bat_instance_check.py —— 按用户真实路径验证单实例（bat → pythonw）

依次启动两个 启动Demo.bat，统计 demo_main 真实进程数（含 shim 链）：
第二个实例的弹窗提示 2.5s 自动关，其进程链应自行退出 → 总数回落。
"""
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "启动Demo.bat"


def demo_procs() -> list[dict]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | "
         "Where-Object {$_.CommandLine -like '*demo_main*'} | "
         "Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    import json
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    return data


def main() -> int:
    subprocess.Popen(["cmd", "/c", "start", "", str(BAT)], cwd=str(ROOT))
    time.sleep(6)
    c1 = demo_procs()
    print(f"实例1 启动 6s 后进程链: {[(p['ProcessId'], p['Name']) for p in c1]}")
    ok1 = len(c1) >= 1
    subprocess.Popen(["cmd", "/c", "start", "", str(BAT)], cwd=str(ROOT))
    time.sleep(4)      # 实例2 弹窗存活期内
    c2 = demo_procs()
    print(f"实例2 弹窗期进程链: {[(p['ProcessId'], p['Name']) for p in c2]}")
    time.sleep(4)      # 实例2 应已自动退出
    c3 = demo_procs()
    print(f"8s 后残留进程链: {[(p['ProcessId'], p['Name']) for p in c3]}")
    ok = ok1 and len(c3) == len(c1)
    print("bat 路径单实例:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
