"""debug/mutex_cross_check.py —— D-027 单实例锁跨进程真实验证

A 进程持有互斥量 → B 进程（新解释器）调用 demo_main.acquire_single_instance()
应返回 False；A 退出后 B 再调应返回 True。
两进程均为真实 OS 进程，等价于"第二个实例"判定路径（不涉及 UI/shim）。
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = Path(r"C:\Users\Stara\.workbuddy\binaries\python\envs\default\Scripts\python.exe")

HOLDER = (
    "import ctypes, time, sys\n"
    "k = ctypes.WinDLL('kernel32', use_last_error=True)\n"
    "k.CreateMutexW(None, False, 'MSI_MousePinyin_Demo_SingleInstance')\n"
    "print('held err=', ctypes.get_last_error(), flush=True)\n"
    "time.sleep(4.0)\n"
)

CHECKER = (
    "import sys\n"
    "sys.path.insert(0, r'%s')\n"
    "from demo_main import acquire_single_instance\n"
    "print('acquire=', acquire_single_instance())\n"
) % str(ROOT)


def run(code: str) -> subprocess.Popen:
    return subprocess.Popen([str(PY), "-X", "utf8", "-c", code],
                            cwd=str(ROOT),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8")


def main() -> int:
    a = run(HOLDER)
    time.sleep(1.5)                     # A 已持锁
    b1 = run(CHECKER)
    out1, _ = b1.communicate(timeout=30)
    time.sleep(3.5)                     # A 已退出
    b2 = run(CHECKER)
    out2, _ = b2.communicate(timeout=30)
    a.wait(timeout=10)
    print("A 输出:", a.stdout.read().strip() if a.stdout else "(空)")
    print("持锁时 B:", out1.strip().replace("\n", " | "))
    print("A 退后 B:", out2.strip().replace("\n", " | "))
    ok = ("acquire= False" in out1) and ("acquire= True" in out2)
    print("D-027 跨进程互斥量:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
