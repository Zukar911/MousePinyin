"""demo_main.py —— P4 前夜版：Dock 字母树拼字 + 键盘模拟（微软拼音承接选字）

使用前准备：
1. 确保微软拼音处于中文模式（或任意拼音输入法）
2. 先点开一个输入框（记事本/微信/浏览器地址栏）——本程序不抢焦点，
   模拟按键会发往当前焦点窗口
3. 鼠标操作：滚轮选字母 → 左键发键 → 拼到音节自动进选字 → 滚轮选字 左键上屏
   X1=拼字/选字切换  X2=退格  ✕ 或 Ctrl+Alt+Q 退出
4. 单实例：重复启动会提示并退出（D-027 命名互斥量）
"""

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QMetaObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from core.candidate_model import CandidateModel
from core.events import Action, Event, Mode
from core.state_machine import StateMachine
from io_sink.keyboard_sink import KeyboardSink
from ui.candidate_window import CandidateWindow

_MUTEX_NAME = "MSI_MousePinyin_Demo_SingleInstance"
_mutex_handle = None
# use_last_error=True：直接调 windll.kernel32.GetLastError() 会被 ctypes 内部
# 调用覆盖（实测两实例并存的根因），必须用 ctypes.get_last_error()
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def acquire_single_instance() -> bool:
    """D-027 单实例锁：Windows 命名互斥量；已有实例时返回 False。"""
    global _mutex_handle
    _mutex_handle = _k32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() != 183   # ERROR_ALREADY_EXISTS


def install_quit_hotkey(app: QApplication) -> None:
    """全局退出热键 Ctrl+Alt+Q（D-009 手写组合判定）。"""
    from pynput import keyboard

    held: set = set()
    MODS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
            keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr}

    def on_press(k):
        held.add(k)
        if k in MODS:
            return
        if any(m in held for m in MODS) and getattr(k, "vk", None) == 81:  # Q
            QMetaObject.invokeMethod(app, "quit", Qt.QueuedConnection)
        held.discard(k)

    def on_release(k):
        held.discard(k)

    kl = keyboard.Listener(on_press=on_press, on_release=on_release)
    kl.daemon = True
    kl.start()


def install_crash_logger() -> None:
    """D-034：pythonw 模式 sys.stderr/stdout 为 None——任何异常的 traceback
    打印会二次失败并级联退出（且堆栈全丢，无法排查）。重定向到 logs 文件
    + 全局 excepthook，崩溃后 logs/stderr.log 可查。
    T-021：打包态写到 exe 旁（app_dir），开发态仍为仓库根。"""
    import time as _time
    import traceback as _tb
    from core.app_paths import app_dir
    log_dir = app_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    f = open(log_dir / "stderr.log", "a", encoding="utf-8", buffering=1)
    sys.stderr = f
    sys.stdout = f

    def _hook(tp, val, tb):
        f.write(f"\n=== UNCAUGHT {_time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        _tb.print_exception(tp, val, tb, file=f)
        f.flush()
    sys.excepthook = _hook


def main() -> int:
    install_crash_logger()
    if not acquire_single_instance():
        # 重复启动：轻量提示后退出（D-027）
        from PySide6.QtWidgets import QMessageBox
        tmp = QApplication(sys.argv)
        box = QMessageBox(QMessageBox.Information, "鼠标拼音输入",
                          "程序已在运行中（屏幕底部键帽条），请勿重复启动。")
        QTimer.singleShot(2500, box.accept)
        box.exec()
        return 0
    app = QApplication(sys.argv)
    # D-023 修复"设置完闪退"：主窗口是 Qt.Tool，不计入 lastWindowClosed 防护，
    # 设置对话框一关就会被 Qt 判定"最后窗口已关"→ 退出。改为 False + closeEvent 显式 quit。
    app.setQuitOnLastWindowClosed(False)

    # D-030 临时调试状态框（仅 --debug-panel 启用时创建，普通启动零开销）
    debug = "--debug-panel" in sys.argv
    panel = collector = None
    if debug:
        from debug.debug_panel import DebugPanel
        panel = DebugPanel(cfg=None, get_dock_info=lambda: "（Dock 信息稍后接入）")

    model = CandidateModel()
    from ui.theme import load_config
    cfg = load_config()                          # D-049：三键开关等读取一次
    sm = StateMachine(model)
    sm.three_key = bool(cfg.three_key)           # D-049 三键模式
    sink = KeyboardSink()
    key_log: list[str] = []
    # D-053 导航门闸：SEND_SPACE 上屏确认后，组合状态未再确认（IME 反馈
    # 未返回）前，SELECT 导航键（↑↓/Space/PgDn）不盲发——组合可能已结束，
    # 盲发的 ↑ 会落入聊天类输入框并被解释为"调出上一条已发送消息全文"
    # （用户实测报告：WorkBuddy 输入框偶发调出以前发送的消息）。
    ime_gate = {"on": False}

    def render() -> None:
        win.render(sm.snapshot(), "".join(key_log)[-20:])
        if panel is not None:
            ime = (f"已发键记录：{''.join(key_log)[-20:] or '（无）'}"
                   if sm.mode is Mode.SELECT else
                   f"已发键记录（最近）：{''.join(key_log)[-20:] or '（无）'}")
            panel.update_status(sm.snapshot(), ime)

    def dock_info() -> str:
        g = win.frameGeometry()
        scr = win.windowHandle().screen() if win.windowHandle() else None
        ax = win.x() + win.width() // 2
        return (f"坐标({win.x()},{win.y()}) 尺寸{win.width()}×{win.height()} "
                f"顶边中心锚点({ax},{win.y()}) 所在屏 {scr.name() if scr else '?'}"
                f"{'（负坐标屏）' if scr and (scr.geometry().left() < 0 or scr.geometry().top() < 0) else ''}")

    def interpret(act, bs, as_, bm, am):
        from core.events import Action
        if act is Action.SEND_LETTER:
            if bs != as_ and as_ == "FINAL_HEAD":
                return "确认当前项（声母整发）→ 进入韵头选择"
            if bs != as_ and as_ == "DONE":
                return "确认韵母（整发）→ 音节完成"
            return "确认当前项（发键）"
        if act is Action.BACKSPACE:
            n = sm.pending_text if sm.pending_text.isdigit() else "1"
            return f"撤销当前音节（计划退格 ×{n}）"
        if act is Action.SEND_SPACE:
            return "选字确认（空格上屏，由输入法定）"
        if act is Action.SEND_PAGEDOWN:
            return "候选翻页（PageDown）"
        if act is Action.FIXUP:
            n, _, letters = (sm.pending_text or "0|").partition("|")
            return f"三键校正：退格×{n} 后发送 '{letters}'"
        if act.name == "NONE":
            if bm != am:
                return "切换模式（拼字 ↔ 选字）"
            return "状态更新（不发键）"
        return f"动作 {act.name}"

    def plan_desc(act, sm) -> str:
        from core.events import Action
        if act is Action.SEND_LETTER:
            return f"发送字母串 '{sm.pending_text}'"
        if act is Action.BACKSPACE:
            n = sm.pending_text if sm.pending_text.isdigit() else "1"
            return f"发送 Backspace ×{n}"
        return {Action.SEND_UP: "发送 ↑", Action.SEND_DOWN: "发送 ↓",
                Action.SEND_SPACE: "发送 Space（上屏）",
                Action.SEND_PAGEDOWN: "发送 PageDown（翻页）"}.get(act, "无输出动作")

    def handle(ev) -> None:
        op = collector.take_op(f"事件 {ev.name}") if collector else None
        bs, bm = sm.stage.name, sm.mode.name
        bidx = sm.idx
        act = sm.handle(ev)
        as_, am = sm.stage.name, sm.mode.name
        idx_moved = sm.idx != bidx
        state = (f"{bs}→{as_}" if bs != as_ else
                 (f"{bm}→{am}" if bm != am else "状态不变"))
        interp = interpret(act, bs, as_, bm, am) if collector else None
        plan = plan_desc(act, sm) if collector else None
        # D-053 导航门闸：确认后第一次导航先校验组合状态再决定发不发
        if (ime_gate["on"] and sm.mode is Mode.SELECT
                and act.name in ("SEND_UP", "SEND_DOWN", "SEND_PAGEDOWN",
                                 "SEND_SPACE")):
            from io_sink.ime_feedback import query_composition
            istate, remaining = query_composition(sm.prefix, retries=1,
                                                  delay=0.05)
            sm.update_composition(remaining, istate)
            ime_gate["on"] = False
            if collector:
                collector.emit(f"{op or '导航门闸'}（D-053）",
                               f"组合状态={istate} → "
                               f"{'拦截不发（组合已结束）' if istate == 'ENDED' else '放行'}",
                               state, "无输出动作" if istate == "ENDED" else "放行后正常发键")
            if istate == "ENDED":
                sm.end_select_session()
                render()
                return
        if act.name in ("SEND_LETTER", "BACKSPACE"):
            if collector:
                collector.expect_execution(plan)
            sink.execute(act, sm.pending_text)   # 字母串 / 退格次数
            if collector:
                collector.emit(op, interp, state, plan)
        elif act.name != "NONE":
            if collector:
                collector.expect_execution(plan)
            sink.execute(act, "")
            if collector:
                collector.emit(op, interp, state, plan)
            # D-031：SELECT 确认键已发 → 组合状态未定，延迟读 IME 反馈；
            # D-053：反馈返回前导航键被门闸拦截
            if act is Action.SEND_SPACE and sm.mode is Mode.SELECT:
                ime_gate["on"] = True
                QTimer.singleShot(180, lambda: ime_feedback_check("选字确认后"))
        else:
            if collector:
                collector.emit(op, interp, state, "无输出动作")
            render()

    def ime_feedback_check(reason: str) -> None:
        """发键 180ms 后读回目标应用文本，判定组合状态（D-031）。
        COMPOSING → 保持选字并同步剩余；ENDED → 清空会话回声母层；
        UNKNOWN → 保持选字 + 明确标注未知（不清空、不补发键）。
        反馈返回后解除 D-053 导航门闸（无论结果）。"""
        from io_sink.ime_feedback import COMPOSING, ENDED, query_composition
        state, remaining = query_composition(sm.prefix)
        sm.update_composition(remaining, state)
        ime_gate["on"] = False
        if collector:
            read = (f"读取通道成功，剩余组合={remaining!r}" if remaining is not None
                    else "读取失败/无法比对 → 标记未知")
            collector.emit(f"{reason}（IME 反馈）",
                           {"COMPOSING": "组合仍在 → 保持选字模式",
                            ENDED: "组合已结束 → 清空会话回声母层",
                            }.get(state, "组合状态未知 → 保持选字，不清空不补发"),
                           f"选字→{'选字' if state != ENDED else '声母层'}",
                           "无输出动作（仅读取）" if state != ENDED else "无输出动作")
        render()

    def on_sent(text: str, ok: bool) -> None:
        if ok and text:
            key_log.append(text)
        render()

    sink.sent.connect(on_sent)

    def on_cap_click(idx: int) -> None:
        """键帽确认：按左键语义确认（发声母/韵母/选字全走原管线）。"""
        sm.idx = idx
        handle(Event.LEFT)

    # T-014 P4 全局模式：--global 启用 io_source/pynput_source.py 全局钩子
    # （全局鼠标钩子 + 区域感知 + Ctrl+Alt+M 开关；Qt 鼠标路径同步抑制）
    global_hook = "--global" in sys.argv
    hook_source = None
    hook_enabled = {"on": True}

    win = CandidateWindow(event_hook=handle, on_cap_click=on_cap_click,
                          global_mode=global_hook)
    win.on_config_changed = lambda c: (
        setattr(sm, "three_key", c.three_key),
        hook_source.set_wheel_sens(c.wheel_sens) if hook_source else None)
    win.render(sm.snapshot(), "")
    win.show()

    if global_hook:
        from PySide6.QtGui import QCursor
        from io_source.pynput_source import PynputHookSource

        def dock_rect():
            g = win.frameGeometry()
            return (g.x(), g.y(), g.width(), g.height())

        def button_rects():
            """⚙/✕/⠿ 全局矩形（钩子判定放行区，按钮点击继续由 Qt 处理）。"""
            out = []
            for b in (win.btn_settings, win.btn_close, win.btn_move):
                gp = b.mapToGlobal(b.rect().topLeft())
                out.append((gp.x(), gp.y(), b.width(), b.height()))
            return out

        hook_source = PynputHookSource(
            dock_rect, button_rects,
            enabled_fn=lambda: hook_enabled["on"],
            wheel_sens=cfg.wheel_sens)

        def on_semantic(ev):
            ev2 = hook_source.interpret(ev, QCursor.pos())
            if ev2 is not None:
                handle(ev2)

        def on_toggle(on: bool):
            hook_enabled["on"] = on
            win.setVisible(on)      # 关闭 = Dock 隐藏 + 事件全放行；再按恢复
            if panel is not None:
                panel.update_status(sm.snapshot(),
                                    f"输入会话{'开启' if on else '关闭'}（Ctrl+Alt+M）")

        hook_source.semantic.connect(on_semantic)
        hook_source.toggled.connect(on_toggle)
        hook_source.start()

    install_quit_hotkey(app)

    if debug:
        from debug.debug_panel import DebugCollector
        panel._get_dock_info = dock_info   # 接入真实 Dock 几何
        collector = DebugCollector(sink, panel)
        win.on_debug = collector.raw_op
        panel.update_status(sm.snapshot())
        panel.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
