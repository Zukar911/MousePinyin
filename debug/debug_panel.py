"""debug/debug_panel.py —— 临时调试状态框（D-030，仅调试用，非最终产品）

组成：
- DebugPanel：独立固定尺寸窗口（置顶/不抢焦点/不参与 Dock 布局），显示
  当前状态 + 最近 100 条操作记录 + 清空按钮；关闭 = 仅隐藏，不退程序。
- DebugCollector：记录聚合器——接收"原始操作"（CandidateWindow 旁路回调）
  与"输出层实际执行"（KeyboardSink.executed 真实执行路径信号），在
  demo_main.handle 中聚合为完整记录（时间→原始操作→程序解释→状态变化→
  计划动作→实际执行）。不监听任何事件源，纯旁路，零行为影响。

诚实原则：发键接口执行成功只代表接口调用成功，目标输入法是否接收/汉字
是否上屏**未读取、未确认**——每条发键记录固定标注"目标接收/上屏：未确认"。
内部拼音缓冲只是程序内部值，不代表目标应用实际文本。
"""

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

STAGE_NAME = {"INITIAL": "声母", "FINAL_HEAD": "韵头", "FINAL_TAIL": "韵母",
              "DONE": "完成"}
MODE_NAME = {"PINYIN": "拼字", "SELECT": "选字"}


def _fmt_highlight(snap) -> str:
    """高亮项：显示文字 | 内部值 | 索引；零声母明确标注。"""
    if not snap.items:
        return "（无候选）"
    idx = snap.idx % len(snap.items)
    raw = snap.items[idx]
    disp = raw if raw.strip() else ""
    head = "零声母（空字符串）" if not raw.strip() else ""
    shown = f"显示'〇'/{head}" if not raw.strip() else f"显示'{disp}'"
    return f"{shown} ｜ 内部值 {raw!r} ｜ 索引 {idx}"


class DebugPanel(QWidget):
    """独立调试窗口：固定尺寸、置顶、不抢焦点、关闭仅隐藏。"""

    def __init__(self, cfg, get_dock_info):
        super().__init__()
        self._get_dock_info = get_dock_info   # 返回 Dock 几何/锚点/所在屏描述
        self.setWindowTitle("调试状态（临时 · --debug-panel）")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(600, 640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        self.lbl_state = QLabel("（等待状态…）")
        self.lbl_state.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_state.setTextFormat(Qt.RichText)
        self.lbl_state.setStyleSheet(
            "QLabel{background:rgba(30,32,40,220);color:#d8e0f0;"
            "font-family:Consolas,Microsoft YaHei;font-size:12px;"
            "border:1px solid #556;padding:6px;border-radius:6px;}")
        lay.addWidget(self.lbl_state)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(100)     # 最近 100 条
        self.log.setStyleSheet(
            "QPlainTextEdit{background:rgba(24,26,32,230);color:#c0e0b8;"
            "font-family:Consolas,Microsoft YaHei;font-size:11px;"
            "border:1px solid #556;}")
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        btn_clear = QPushButton("清空记录")
        btn_clear.clicked.connect(self.clear_records)
        row.addWidget(btn_clear)
        row.addStretch(1)
        tip = QLabel("发键成功≠输入法已接收；上屏结果：未确认")
        tip.setStyleSheet("color:#889;font-size:11px;")
        row.addWidget(tip)
        lay.addLayout(row)

    # ---------- 状态区 ----------

    def update_status(self, snap, ime_info: str = "") -> None:
        info = self._get_dock_info() if self._get_dock_info else "—"
        stage = STAGE_NAME.get(snap.stage.name, snap.stage.name)
        mode = MODE_NAME.get(snap.mode.name, snap.mode.name)
        if snap.mode.name == "SELECT":
            comp = (f"剩余组合（读回，可信）：{snap.composition!r}"
                    if snap.composition is not None
                    else f"剩余组合：未知/未确认（内部缓冲 {snap.prefix or '空'}，不冒充实际值）")
        else:
            comp = "（非选字模式）"
        self.lbl_state.setText(
            f"<b>模式</b>：{mode} ｜ <b>阶段</b>：{stage}<br>"
            f"<b>高亮</b>：{_fmt_highlight(snap)}<br>"
            f"<b>当前音节</b>：{snap.syllable or '（空）'} ｜ "
            f"<b>内部拼音缓冲</b>：{snap.prefix or '（空）'}（程序内部值，非目标文本）<br>"
            f"<b>组合状态</b>：{comp} ｜ {ime_info}<br>"
            f"<b>Dock</b>：{info}")

    # ---------- 记录 ----------

    def append_record(self, line: str) -> None:
        self.log.appendPlainText(line)

    def clear_records(self) -> None:
        self.log.clear()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.hide()                # 仅关闭调试显示，不退出输入程序
        e.ignore()


class DebugCollector:
    """记录聚合器：组装"原始操作→解释→状态变化→计划→实际执行"五段记录。

    数据来源（全部旁路）：
    - raw_op()：CandidateWindow 在滚轮/按键事件中提供的原始操作描述
    - sm 前后快照：demo_main.handle 中采集（不重复执行事件）
    - KeyboardSink.executed：输出层真实执行详情（含异常）
    """

    def __init__(self, sink, panel: DebugPanel):
        self.panel = panel
        self._pending_op: str | None = None
        self._pending_actual: str | None = None
        self._pending_ok: bool | None = None
        self._records = deque(maxlen=100)
        sink.executed.connect(self._on_executed)

    # ---------- 原始操作（CandidateWindow 旁路） ----------

    def raw_op(self, desc: str, instant: bool = False) -> None:
        """instant=True：操作自带完整语义（如滚轮未达阈值），立即独立落记录；
        否则暂存，等待 handle 聚合后续阶段（状态变化/计划/实际执行）。"""
        if instant:
            self.emit(desc, "—", "—", "无输出动作")
        else:
            self._pending_op = desc

    def take_op(self, fallback: str) -> str:
        op = self._pending_op or fallback
        self._pending_op = None
        return op

    # ---------- 输出层实际执行 ----------

    def expect_execution(self, plan: str) -> None:
        self._pending_actual = "（等待执行结果…）"
        self._pending_ok = None
        self._plan = plan

    def _on_executed(self, desc: str, ok: bool) -> None:
        self._pending_actual = desc
        self._pending_ok = ok

    # ---------- 快照与解释 ----------

    @staticmethod
    def snap(sm) -> str:
        stage = STAGE_NAME.get(sm.stage.name, sm.stage.name)
        hl = _fmt_highlight(sm.snapshot()) if sm.items else "（无）"
        return (f"{MODE_NAME.get(sm.mode.name, sm.mode.name)}[{stage}] "
                f"高亮({hl}) idx={sm.idx % max(1, len(sm.items)) if sm.items else 0}")

    @staticmethod
    def interpret(sm, act, before_stage, after_stage, before_mode, after_mode,
                  idx_moved: bool) -> str:
        from core.events import Action
        if act is Action.SEND_LETTER:
            if before_stage != after_stage:
                if after_stage == "FINAL_HEAD":
                    return "确认当前项（声母整发）→ 进入韵头选择"
                if after_stage == "DONE":
                    return "确认韵母（整发）→ 音节完成"
                if before_stage == "INITIAL":
                    return "确认当前项 → 阶段推进"
            return "确认当前项（发键）"
        if act is Action.BACKSPACE:
            n = sm.pending_text if sm.pending_text.isdigit() else "1"
            return f"撤销当前音节（计划退格 ×{n}）"
        if act is Action.SEND_SPACE:
            return "选字确认（空格上屏，由输入法定）"
        if act is Action.SEND_PAGEDOWN:
            return "候选翻页（PageDown）"
        if act is Action.SEND_UP or act is Action.SEND_DOWN:
            return "候选高亮移动（选字模式）"
        if act.name == "NONE":
            if before_mode != after_mode:
                return "切换模式（拼字 ↔ 选字）"
            if idx_moved:
                return "仅移动高亮（不发键）"
            return "状态不变（不发键）"
        return f"动作 {act.name}"

    # ---------- 落盘一条记录 ----------

    def emit(self, op: str, interp: str, state_chg: str,
             plan: str) -> None:
        import time
        actual = self._pending_actual or "—（无输出动作）"
        ok = self._pending_ok
        tail = ""
        if ok is True:
            tail = " ｜ 目标接收/上屏：未确认（未读取输入法状态）"
        elif ok is False:
            tail = " ｜ 输出层报告失败"
        line = (f"{time.strftime('%H:%M:%S')} ｜ {op} ｜ {interp} ｜ {state_chg} ｜ "
                f"计划：{plan} ｜ 实际：{actual}{tail}")
        self._records.append(line)
        self._pending_actual = None
        self._pending_ok = None
        if self.panel:
            self.panel.append_record(line)
