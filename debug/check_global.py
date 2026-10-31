"""debug/check_global.py —— T-014 --global 模式真桌面端到端验证

真实全局钩子链（pynput Listener → 系统合成事件 → 主线程 interpret → 状态机），
FakeSink 不发真键（D-031 教训）。合成鼠标用**自校准**（pynput set/get 偏差
动态补偿——多屏混合 DPI 下 pynput 坐标与 Qt 逻辑坐标存在错位风险，
spike_global_hook 中间轮实测）。

检查项：
  G1 全局钩子驱动 Dock：窗内合成滚轮 → idx 变化（唯一事件源）
  G2 窗外零投递：窗外合成滚轮 → idx 不变
  G3 左键确认：Dock 空白区合成左键 → 状态机确认（INITIAL→FINAL_HEAD）
  G4/G5 Ctrl+Alt+M 关闭/恢复：Dock 隐藏 + 事件放行；再按恢复
  G6 Qt 事件路径已抑制：向窗口直发合成 Qt 滚轮 → idx 不变（无双份）
  G7 按钮区放行：⚙ 上合成左键 → 按钮 clicked 触发 + 语义零投递
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QCursor, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.candidate_model import CandidateModel  # noqa: E402
from core.events import Event  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402
from io_source.pynput_source import PynputHookSource  # noqa: E402
from ui.candidate_window import CandidateWindow  # noqa: E402

CONFIG = ROOT / "data" / "config.json"
BACKUP = ROOT / "data" / "config.json.harnessbak"

PASS, FAIL = [], []
SC = {"sx": 1.0, "sy": 1.0, "bx": 0.0, "by": 0.0}   # set = (qt-b)/s 线性映射


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f" | {detail}" if detail else ""))


class FakeSink:
    def execute(self, action, payload: str = "") -> None:
        pass


def pump(ms: int) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def goto(mc, x: int, y: int) -> None:
    """按两点标定的线性映射移动到 Qt 逻辑坐标 (x, y)。"""
    mc.position = ((x - SC["bx"]) / SC["sx"], (y - SC["by"]) / SC["sy"])
    time.sleep(0.12)


def calibrate(mc) -> None:
    """两点标定 pynput set → Qt 逻辑 的线性映射（DPI 缩放是比例差，
    单点校准只学到偏移、到别处仍有残差——spike/check_global 首版教训）。"""
    def probe(sx, sy):
        mc.position = (sx, sy)
        time.sleep(0.15)
        return QCursor.pos()
    q1 = probe(500, 400)
    q2 = probe(900, 700)
    SC["sx"] = (q2.x() - q1.x()) / 400.0
    SC["sy"] = (q2.y() - q1.y()) / 300.0
    SC["bx"] = q1.x() - SC["sx"] * 500
    SC["by"] = q1.y() - SC["sy"] * 400
    goto(mc, 650, 500)
    qv = QCursor.pos()
    err = max(abs(qv.x() - 650), abs(qv.y() - 500))
    print(f"  标定 s=({SC['sx']:.3f},{SC['sy']:.3f}) b=({SC['bx']:.0f},{SC['by']:.0f}) "
          f"验证误差 {err}px")
    if err > 4:                      # 残差迭代补偿（局部线性）
        goto(mc, 650, 500)
        qv = QCursor.pos()
        SC["bx"] += qv.x() - 650
        SC["by"] += qv.y() - 500


def wheel_evt(dy: int) -> QWheelEvent:
    pos = QPointF(300, 20)
    return QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, dy),
                       Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)


def main() -> int:
    shutil.copy(CONFIG, BACKUP)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    sm = StateMachine(CandidateModel())
    sink = FakeSink()

    def handle(ev: Event) -> None:
        act = sm.handle(ev)
        sink.execute(act, sm.pending_text)
        win.render(sm.snapshot(), "")

    win = CandidateWindow(event_hook=handle, global_mode=True)
    win.cfg.wheel_sens = 2
    win.render(sm.snapshot(), "")
    win.show()
    pump(400)

    hook_enabled = {"on": True}

    def button_rects():
        gp = win.btn_settings.mapToGlobal(QPoint(0, 0))
        return [(gp.x(), gp.y(), win.btn_settings.width(),
                 win.btn_settings.height())]

    src = PynputHookSource(
        lambda: (win.x(), win.y(), win.width(), win.height()),
        button_rects,
        enabled_fn=lambda: hook_enabled["on"],
        wheel_sens=2)

    def on_semantic(ev):
        ev2 = src.interpret(ev, QCursor.pos())
        if ev2 is not None:
            handle(ev2)

    src.semantic.connect(on_semantic)
    src.start()
    pump(200)

    from pynput.keyboard import Controller as KController, Key
    from pynput.mouse import Button, Controller as MController
    mc, kc = MController(), KController()
    calibrate(mc)

    n = len(sm.items)
    dx = win.x() + win.width() // 2
    dy_ = win.y() + win.height() // 2

    print("== T-014 --global 全局钩子链（真桌面） ==")

    # G1 窗内滚轮 → idx 变化
    idx0 = sm.idx
    goto(mc, dx, dy_)
    mc.scroll(0, -2)                    # 2 格 = 1 项（sens=2），SCROLL_DOWN = idx+1
    pump(400)
    check("G1 窗内合成滚轮经全局钩子驱动 Dock",
          sm.idx == (idx0 + 1) % n, f"idx {idx0}→{sm.idx}")

    # G6 Qt 路径已抑制（无双份）：直发合成 Qt 滚轮 → 不应变化
    idx1 = sm.idx
    QApplication.sendEvent(win, wheel_evt(-120))
    pump(200)
    check("G6 Qt 事件路径已抑制（无双重处理）", sm.idx == idx1,
          f"idx 保持 {sm.idx}")

    # G2 窗外滚轮 → 零投递
    goto(mc, 500, 300)                  # 屏幕中央空白（Dock 外）
    mc.scroll(0, -4)
    pump(400)
    check("G2 窗外合成滚轮零投递", sm.idx == idx1, f"idx 保持 {sm.idx}")

    # G3 左键确认（Dock 空白区）
    stage0 = sm.stage.name
    goto(mc, win.x() + 40, dy_)         # 键帽行左侧空白
    mc.click(Button.left)
    pump(400)
    check("G3 左键确认走全局钩子（状态机推进）",
          sm.stage.name != stage0,
          f"{stage0}→{sm.stage.name} idx={sm.idx}")

    # X2 撤销回声母层（保持状态干净，为热键项铺路）
    handle(Event.X2)
    pump(100)

    # G4 Ctrl+Alt+M 关闭（与 demo_main.on_toggle 同款接线：Dock 隐藏/恢复）
    states = []
    src.toggled.connect(states.append)
    src.toggled.connect(lambda on: (hook_enabled.__setitem__("on", on),
                                    win.setVisible(on)))
    kc.press(Key.ctrl); kc.press(Key.alt); kc.press("m")
    time.sleep(0.12)
    kc.release("m"); kc.release(Key.alt); kc.release(Key.ctrl)
    pump(400)
    hidden = not win.isVisible()
    idx_frozen = sm.idx
    goto(mc, dx, dy_)
    mc.scroll(0, -2)
    pump(300)
    check("G4 Ctrl+Alt+M 关闭：Dock 隐藏 + 会话事件放行",
          hidden and states == [False] and sm.idx == idx_frozen,
          f"visible={win.isVisible()} states={states} idx 保持 {sm.idx}")

    # G5 再按恢复
    kc.press(Key.ctrl); kc.press(Key.alt); kc.press("m")
    time.sleep(0.12)
    kc.release("m"); kc.release(Key.alt); kc.release(Key.ctrl)
    pump(400)
    check("G5 Ctrl+Alt+M 恢复：Dock 显示",
          win.isVisible() and states == [False, True],
          f"visible={win.isVisible()} states={states}")

    # G7 按钮区放行（⚙：clicked 由 Qt 处理；语义零投递）
    clicked = []
    win.open_settings = lambda: clicked.append(1)   # 拦截真开窗
    idx2 = sm.idx
    gp = win.btn_settings.mapToGlobal(QPoint(13, 13))
    goto(mc, gp.x(), gp.y())
    mc.click(Button.left)
    pump(400)
    check("G7 ⚙ 按钮区放行（Qt 处理 + 语义零投递）",
          bool(clicked) and sm.idx == idx2,
          f"clicked={clicked} idx 保持 {sm.idx}")

    src.stop()
    print(f"\nharness 结果：PASS={len(PASS)} FAIL={len(FAIL)}")
    shutil.copy(BACKUP, CONFIG)         # 恢复用户配置（含位置）
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
