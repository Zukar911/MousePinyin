"""debug/check_residual.py —— 真实桌面残留问题检查 harness（T-040 阶段）

对照工作文档中"已标记解决"的各决策，在真实 Windows 桌面（真窗口、
合成鼠标/滚轮事件）逐项复测；FakeSink 不注入任何真实按键（D-031
WorkBuddy 污染教训——真实发键验证永远留给用户手测）。

覆盖清单：
  D-025 滚轮事件上浮（dock→父窗口转发）
  D-025/D-028⑤ 缩放/层切换顶边中心锚点稳定
  D-026 focusPos 动画真实到位
  D-028① 任意焦点位置不裁切  ② 环形回绕瞬移
  D-028③⑥ 滚轮 delta 累积（sens=1/2）  ⑦ X2 撤销音节回声母层全显
  D-023 设置界面开→滑→关后程序存活（闪退回归）
  D-029 负坐标副屏上切层/缩放锚点不跳屏
  D-032/D-033 左键统一确认滚轮选中项（坐标无关）
  D-034 动画全程未选中键帽中心/尺寸零变化（真平台）
  D-022 ⚙/✕/⠿ 按钮样式表可解析（真平台 QSS 回归）
  D-027 单实例锁（真进程级，另测：second_instance_check）
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.candidate_model import CandidateModel  # noqa: E402
from core.events import Action, Event  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402
from ui.candidate_window import CandidateWindow  # noqa: E402
from ui.dock_strip import DockStrip, cap_units  # noqa: E402

CONFIG = ROOT / "data" / "config.json"
BACKUP = ROOT / "data" / "config.json.harnessbak"

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + (f" | {detail}" if detail else ""))


class FakeSink:
    """不发真键：仅满足 demo_main.handle 的调用形状。"""

    def execute(self, action, payload: str = "") -> None:
        pass


def wheel_evt(dy: int) -> QWheelEvent:
    """合成滚轮：dy<0（向下滚）= SCROLL_DOWN = idx+1；dy>0 = idx-1。"""
    pos = QPointF(300, 20)
    return QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, dy),
                       Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)


def left_press(w) -> None:
    posf = QPointF(w.width() - 120.0, w.height() * 0.7)   # 空白/按钮左侧区域
    ev = QMouseEvent(QEvent.MouseButtonPress, posf, posf,
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(w.dock, ev)


def pump(ms: int) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def anchor(win) -> tuple[int, int]:
    return win.x() + win.width() // 2, win.y()


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

    confirmed: list[int] = []

    def on_cap_click(idx: int) -> None:
        confirmed.append(idx)
        handle(Event.LEFT)

    win = CandidateWindow(event_hook=handle, on_cap_click=on_cap_click)
    win.cfg.wheel_sens = 1                      # 测试基准：1 格/项
    win.render(sm.snapshot(), "")               # 与 demo_main 一致：show 前首渲染
    win.show()
    pump(300)
    n_items = len(sm.items)
    base_cx = list(win.dock._cx)                 # D-035 基线中心（左端钉死断言用）

    print("== D-022 ⚙/✕/⠿ 样式表解析（真平台回归） ==")
    from ui.candidate_window import btn_css
    css = btn_css("#c8d2ee")
    balanced = css.count("{") == css.count("}")
    win.btn_settings.setStyleSheet(css)         # 解析失败会在 stderr 打警告
    pump(100)
    check("btn_css 花括号平衡且可解析", balanced and css.rstrip().endswith("}"),
          f"braces {css.count('{')}/{css.count('}')}")

    print("== D-035 左锚定等比鱼眼：锚点恒定 + 焦点到位（真平台） ==")
    d0 = win.dock
    x0_ref, e_ref = d0._x0, d0._e_ref
    QApplication.sendEvent(win, wheel_evt(-120))  # 0→1
    pump(60)                                     # 动画进行中
    check("动画中 _x0/_e_ref 不变", d0._x0 == x0_ref and d0._e_ref == e_ref)
    pump(300)                                    # 动画结束
    check("D-026 动画真实到位 focus≈1", abs(d0._focus - 1.0) < 0.01,
          f"focus={d0._focus:.2f}")
    check("状态机 idx 同步", sm.idx == 1, f"idx={sm.idx}")

    print("== D-035 真平台像素回归：远离焦点区动画前后一致 ==")
    from PySide6.QtCore import QRect
    win.dock._anim.stop()
    win.dock.set_focus(20.0)
    win.dock.repaint()
    img_a = win.dock.grab().toImage()
    x1 = int(win.dock._cx[3])
    reg_a = (img_a.width(), img_a.height(),
             bytes(img_a.copy(QRect(0, 0, x1, img_a.height())).constBits()))
    win.dock.set_focus(21.4)                    # 过渡帧
    win.dock.repaint()
    img_b = win.dock.grab().toImage()
    reg_b = (img_b.width(), img_b.height(),
             bytes(img_b.copy(QRect(0, 0, x1, img_b.height())).constBits()))
    # D-036 环形语义：f=23 时 0 号是缝合邻居（保持放大），行中远帽仍钉基线
    win.dock.set_focus(23.0)
    win.dock.repaint()
    seam_ok = win.dock._scale_of(0, 23.0) > 1.5
    win.dock.set_focus(12.0)
    win.dock.repaint()
    mid_pinned = (all(abs(win.dock._scale_of(i, 12.0) - 1.0) < 1e-9
                      for i in range(0, 9))
                  and all(abs(win.dock._cx[i] - base_cx[i]) < 0.01
                          for i in range(0, 9)))
    win.dock.set_focus(20.0)                    # 复位
    check("左端 3 帽区域像素逐字节一致", reg_a == reg_b)
    check("D-036 焦点 23 时 0 号缝合邻居保持放大 >1.5", seam_ok)
    check("D-036 焦点 12 时左端 0..8 帽钉在基线", mid_pinned)

    print("== D-028③⑥/D-038 滚轮累积器（第一档=2 格/项） ==")
    win.cfg.wheel_sens = 2
    win._wheel_acc = 0
    QApplication.sendEvent(win, wheel_evt(-120))  # 一档：240 才动
    check("一档(2格) 单 120 不动", sm.idx == 1, f"idx={sm.idx}")
    QApplication.sendEvent(win, wheel_evt(-120))
    check("一档(2格) 累计 240 动 1 格", sm.idx == 2, f"idx={sm.idx}")
    win.cfg.wheel_sens = 3
    win._wheel_acc = 0
    QApplication.sendEvent(win, wheel_evt(-120))
    QApplication.sendEvent(win, wheel_evt(-120))
    check("三档(3格) 累计 240 不动", sm.idx == 2, f"idx={sm.idx}")
    QApplication.sendEvent(win, wheel_evt(-120))
    check("三档(3格) 累计 360 动 1 格", sm.idx == 3, f"idx={sm.idx}")
    pump(300)

    print("== D-025 滚轮上浮（发往 dock，父窗口必须收到） ==")
    win._wheel_acc = 0
    win.cfg.wheel_sens = 2                    # 一档（240/项）
    posf = QPointF(60, 20)
    ev = QWheelEvent(posf, posf, QPoint(0, 0), QPoint(0, -240),
                     Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(win.dock, ev)
    check("dock.wheelEvent 转发父级生效", sm.idx == 4, f"idx={sm.idx}")
    pump(300)

    print("== D-033 左键统一确认（坐标无关）+ D-028⑤ 层切换锚点 ==")
    sm.idx = 1                                   # 滚轮选中 1
    win.render(sm.snapshot(), "")
    pump(300)
    a0 = anchor(win)
    scr0 = win.screen().availableGeometry()   # 窗口所在屏（多屏环境勿用主屏）
    sel_text = sm.items[1]
    confirmed.clear()
    left_press(win)                              # 鼠标在空白处 → 仍确认 1
    check("左键确认滚轮选中项 1", confirmed == [1], f"{confirmed}")
    check("确认后进入韵头层", sm.stage.name == "FINAL_HEAD",
          f"stage={sm.stage.name} syllable={sm.syllable!r} sel={sel_text!r}")
    pump(200)
    # D-050 固定外框：宽度恒定 → 锚点恒定（含屏外位置——无尺寸变化即无钳制）
    check("层切换顶边中心锚点不动（固定外框）", anchor(win) == a0,
          f"{a0} → {anchor(win)}")
    check("层切换窗口尺寸不变（跟随 dock 容量）",
          win.width() == win.dock.width() + 8, f"w={win.width()}")

    print("== D-029 负坐标副屏锚点稳定（多屏时）/ 单屏钳制（环境自适应） ==")
    multi_screen = len(QApplication.screens()) > 1
    if multi_screen:
        win.move(-1842, 651)
        pump(200)
        a_neg = anchor(win)
        sm.idx = 0
        confirmed.clear()
        left_press(win)                          # 确认韵头首项 → 层切换
        pump(200)
        check("负屏上左键确认成功", len(confirmed) == 1, f"{confirmed}")
        check("负屏层切换锚点稳定", anchor(win) == a_neg,
              f"{a_neg} → {anchor(win)}")
        check("窗口仍在负坐标屏", win.x() < 0, f"x={win.x()}")
    else:
        # 单屏环境（用户当前拔掉副屏/改了显示配置）：验证钳制行为——
        # 移到屏外后层切换应把窗口拉回屏内（D-029 设计）
        win.move(-1500, 400)
        pump(200)
        sm.idx = 0
        confirmed.clear()
        left_press(win)
        pump(200)
        scr = QApplication.primaryScreen().availableGeometry()
        check("单屏：屏外窗口经层切换被钳回屏内",
              win.x() + win.width() > scr.left() and win.x() < scr.right(),
              f"x={win.x()} w={win.width()} avail_left={scr.left()}")

    print("== D-028⑦ X2 撤销回声母层全显 ==")
    handle(Event.X2)
    pump(200)
    check("X2 回到声母层", sm.stage.name == "INITIAL" and len(sm.items) == n_items,
          f"stage={sm.stage.name} items={len(sm.items)}")
    if multi_screen:
        check("X2 后锚点仍稳定", anchor(win) == a_neg, f"{anchor(win)}")
    else:
        scr = QApplication.primaryScreen().availableGeometry()
        check("X2 后窗口仍在屏内（单屏钳制）",
              win.x() + win.width() > scr.left() and win.x() < scr.right(),
              f"x={win.x()}")

    print("== D-039 边缘不裁切/不侵入按钮区（累加排布，端点焦点） ==")
    d1 = win.dock
    ok_all = True
    for f in (0.0, float(n_items - 1)):
        d1._anim.stop()
        d1.set_focus(f)
        d1.repaint()
        img = d1.grab()
        px = img.toImage()
        # 数学（镜像 D-039 峰值保持归一化）：峰值帽不缩放、邻居按剩余预算
        e_raw = d1._energy_units(f) * d1._u
        peak_extra = sum(
            (d1._scale_of(i, f) - 1.0) * cap_units(d1._items[i]) * d1._u
            for i in range(n_items) if d1._ring_dist(i, f) <= 0.5)
        nb_raw = e_raw - peak_extra
        nb_target = d1._e_ref - peak_extra
        if nb_raw > 1e-6 and nb_target > 0:
            k_nb = nb_target / nb_raw
        else:
            k_nb = 0.0 if nb_target <= 0 else 1.0
        x = d1._x0
        first_l = None
        last_r = 0.0
        for i in range(n_items):
            raw = d1._scale_of(i, f)
            if d1._ring_dist(i, f) <= 0.5:
                s = raw
            else:
                s = min(1.0 + (raw - 1.0) * k_nb, 2.05)
            w_i = cap_units(d1._items[i]) * d1._u * s
            if first_l is None:
                first_l = x
            last_r = x + w_i
            x += w_i + d1._gap
        if first_l < d1._x0 - 0.01 or last_r > d1.width() - d1._pad_r + 0.01:
            ok_all = False
    check("端点焦点：行不出左缘/不侵入按钮区", ok_all)

    print("== D-040 缩放单调：调大永不变小（环境自适应） ==")
    if multi_screen:
        win.move(-1842, 651)                     # 副屏：满尺寸可达 1.5×
    pump(150)
    seq_u, seq_w = [], []
    for sc100 in range(70, 151, 5):
        win.cfg.scale = sc100 / 100
        win.dock.set_config(win.cfg)
        pump(30)
        seq_u.append(round(win.dock._u, 4))
        seq_w.append(win.dock.width())
    win.cfg.scale = 1.0
    win.dock.set_config(win.cfg)
    pump(30)
    mono_u = all(b >= a - 1e-6 for a, b in zip(seq_u, seq_u[1:]))
    mono_w = all(b >= a - 1 for a, b in zip(seq_w, seq_w[1:]))
    check("scale 0.7→1.5 键帽 u 单调不减", mono_u, str(seq_u))
    check("scale 0.7→1.5 窗宽单调不减", mono_w, str(seq_w))
    if multi_screen:
        check("副屏 1.3× 键帽满尺寸 u=52", abs((seq_u[12]) - 52.0) < 0.01,
              f"u(1.3)={seq_u[12]}")
    else:
        # 单屏窄幅：u 封顶常数（D-040 诚实边界），验证封顶后仍单调且 ≥ 基准
        capped = max(seq_u)
        check("单屏窄幅：u 封顶常数且 ≥ 40（不回缩不塌缩）",
              capped >= 40.0 and all(abs(x - capped) < 0.6
                                     for x in seq_u[-6:]),
              f"u 序列尾段={seq_u[-6:]} cap={capped}")

    print("== D-039 峰值保持：任何位置落定精确 1.8×，永不缩小 ==")
    ok_peak = True
    for i in range(n_items):
        _, _, sd = __import__("tests.test_fixed_caps",
                              fromlist=["frame_layout"]).frame_layout(d1, float(i))
        if abs(sd[i] - 1.8) > 1e-6:
            ok_peak = False
    check("全位置落定峰值 = 1.8×（含宽帽 zh/ch/sh）", ok_peak)
    import math as _m
    expect_mid = 1.0 + 0.8 * _m.sin(_m.pi / 2 * 0.8)
    ok_transit = True
    for i in range(n_items):
        nxt = (i + 1) % n_items
        _, _, sd = __import__("tests.test_fixed_caps",
                              fromlist=["frame_layout"]).frame_layout(d1, i + 0.5)
        if abs(sd[nxt] - expect_mid) > 1e-6 or sd[nxt] >= 1.8:
            ok_transit = False
    check("过渡峰值恒定 < 落定（放大单调不缩小）", ok_transit)

    print("== D-036 环形连续回绕（无硬切，旧侧渐收） ==")
    from PySide6.QtCore import QAbstractAnimation
    sm.idx = n_items - 1
    win.render(sm.snapshot(), "")
    win._wheel_acc = 0
    win.cfg.wheel_sens = 2
    QApplication.sendEvent(win, wheel_evt(-240))  # 23→0 环绕（一档 240）
    check("环绕 idx 到 0", sm.idx == 0, f"idx={sm.idx}")
    d2 = win.dock
    running = d2._anim.state() == QAbstractAnimation.State.Running
    end_v = d2._anim.endValue()
    check("回绕连续动画（非瞬移）且终点=环上最近等价点",
          running and end_v == float(n_items)
          and abs(end_v - d2._focus) <= n_items / 2,
          f"running={running} end={end_v} focus={d2._focus:.2f}")
    pump(300)
    check("动画完成 focus≈24（≡0）", abs(d2._focus - n_items) < 0.01,
          f"focus={d2._focus:.2f}")
    check("缝合邻居保持放大", d2._scale_of(n_items - 1, d2._focus) > 1.5)

    print("== D-037 焦点无界漂移回归（多次回绕后场不乱） ==")
    d3 = win.dock
    d3._anim.stop()
    d3.set_focus(3.0)
    d3.repaint()
    img_base = d3.grab().toImage()
    d3.set_focus(3.0 + n_items * 9)          # 焦点漂移 9 圈（用户多次滚轮路径）
    d3.repaint()
    img_drift = d3.grab().toImage()
    same = ((img_base.width(), img_base.height(), bytes(img_base.constBits()))
            == (img_drift.width(), img_drift.height(),
                bytes(img_drift.constBits())))
    check("漂移 9 圈后渲染逐字节一致", same)
    d3.set_focus(3.0)

    print("== D-023/D-025 设置界面开→滑→关→存活 + 缩放锚点 ==")
    quit_flag = []
    app.aboutToQuit.connect(lambda: quit_flag.append(True))
    a_pre = anchor(win)
    win.open_settings()
    dlg = win._settings_dlg
    ok_slider = dlg is not None and dlg.isVisible()
    max_drift = 0.0
    for v in (70, 100, 150, 100):
        dlg._sl_set_scale.setValue(v)
        pump(80)
        max_drift = max(max_drift,
                        abs(anchor(win)[0] - a_pre[0]), abs(anchor(win)[1] - a_pre[1]))
    dlg.accept()
    pump(1500)
    check("设置打开且滑条实时应用", ok_slider)
    check("缩放过程顶边锚点漂移 ≤1px", max_drift <= 1.0, f"drift={max_drift}px")
    check("关闭设置 1.5s 后程序存活（闪退回归）",
          not quit_flag and win.isVisible())

    print("== D-038 外观包：皮肤×质感全渲染 + 光标光源照边 ==")
    from ui.theme import SKINS, TEXTURES
    ok_render = True
    for sk in SKINS:
        for tx in TEXTURES:
            win.cfg.skin, win.cfg.texture = sk, tx
            win.dock.set_config(win.cfg)
            win.repaint()
            if win.grab().isNull():
                ok_render = False
    win.cfg.skin, win.cfg.texture = "deepsea", "glass"
    win.dock.set_config(win.cfg)
    win.repaint()
    check("10 皮肤 × 4 质感全渲染无异常", ok_render)
    # 光源照边：光在最左侧时左端边缘像素应比光在最右侧时更亮（暖光）
    def edge_brightness(light_x: float) -> float:
        win.dock._light = QPointF(light_x, win.dock.height() * 0.5)
        win.dock.repaint()
        img = win.dock.grab().toImage()
        total = 0
        for yy in range(0, img.height(), 2):
            for xx in range(0, 60, 2):     # 左端 60px 带
                c = img.pixel(xx, yy)
                total += (c >> 16 & 0xFF) + (c >> 8 & 0xFF) + (c & 0xFF)
        win.dock._light = None
        win.dock.repaint()
        return total
    bright_left = edge_brightness(20.0)
    bright_right = edge_brightness(win.dock.width() - 20.0)
    check("光标光源照亮近侧边缘（左亮 > 右亮）", bright_left > bright_right,
          f"{bright_left} vs {bright_right}")

    print("== D-044 背景采样管线（后台线程 GDI + 主线程零阻塞） ==")
    win.cfg.skin = "ice"                      # 透明皮肤 → 采样器启用
    win.cfg.backdrop = True                   # 用户可能关闭过开关——测试显式开
    win.dock.set_config(win.cfg)
    win._sampler._tick()                      # 手动投一轮（异步 worker）
    got = False
    for _ in range(60):                       # 最多等 3s
        pump(50)
        if win.dock._backdrop is not None:
            got = True
            break
    check("后台采样已产出并分发到键帽层", got)
    if got:
        check("背景尺寸与窗口匹配（DPR 正确）",
              abs(win._sampler.pix.width()
                  - win.width() * win._backdrop_dpr) <= 2
              and abs(win._sampler.pix.height()
                      - win.height() * win._backdrop_dpr) <= 2,
              f"{win._sampler.pix.width()}x{win._sampler.pix.height()} "
              f"dpr={win._backdrop_dpr}")
    # 主线程卡顿度量：采样运行中连续重绘 30 帧的单帧耗时
    import time as _t
    reps = []
    for _ in range(30):
        t0 = _t.perf_counter()
        win.repaint()
        reps.append((_t.perf_counter() - t0) * 1000)
        pump(30)
    check("采样运行中主线程单帧重绘 < 25ms（均值）",
          sum(reps) / len(reps) < 25.0,
          f"avg={sum(reps)/len(reps):.1f}ms max={max(reps):.1f}ms")
    win.repaint()
    # 开关往返：关闭 → 停采样+折射源清空；重开 → 恢复
    win.cfg.backdrop = False
    win.apply_config(win.cfg)
    pump(100)
    check("背景采样开关关闭：折射源清空",
          win.dock._backdrop is None and win._backdrop_pix is None)
    win.cfg.backdrop = True
    win.apply_config(win.cfg)
    win._sampler._tick()
    got2 = False
    for _ in range(60):
        pump(50)
        if win.dock._backdrop is not None:
            got2 = True
            break
    check("背景采样开关重开：采样恢复", got2)
    win.repaint()
    win.cfg.skin = "deepsea"                  # 恢复不透明（backdrop 状态由
    win.dock.set_config(win.cfg)              # harness 末尾的配置还原处理）
    win.repaint()

    win.close()
    pump(200)
    shutil.copy(BACKUP, CONFIG)                  # 恢复用户配置
    BACKUP.unlink()
    print(f"\nharness 结果：PASS={len(PASS)} FAIL={len(FAIL)}")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
