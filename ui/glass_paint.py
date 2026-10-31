"""ui/glass_paint.py —— 玻璃/光效绘制模块（D-048，从 dock_strip 拆出）

职责边界（02 §10.3/10.4 的模块化债清偿第一步）：
  - 本模块只做**绘制**（纯 QPainter 命令，参数进 → 像素出），不做布局/
    交互/状态——布局仍在 dock_strip（鱼眼/锚定），鼠标语义仍在窗口层。
  - 所有函数无 self 依赖，可独立单测/离屏冒烟。

去雾配比（D-048，用户"雾蒙蒙"反馈）——背景折射在场（bd 非 None 且
trans>0.02）时全面减白：磨砂底透明度 0.80→0.86（透更多真桌面）、皮肤
染色 ×0.55→×0.38、顶部流光 ×0.60→×0.45、斜光带 ×0.60、密度环
×0.60→×0.35、倒影带 ×0.60——雾感主要来自白叠加与染色，不是模糊本身。
"""
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainterPath,
                           QPen, QRadialGradient)

NO_PEN = QPen(Qt.NoPen)
MAXS = 1.8


@dataclass
class CapCtx:
    """单个键帽的绘制上下文（纯数据，无窗口依赖）。"""
    rect: QRectF
    r: float
    cx0: float
    u: float
    skin: object            # theme.Skin
    tex: object             # theme.Texture
    glass: float
    trans: float
    selected: bool
    light: object = None    # QPointF | None（光标光源）
    bd: object = None       # QPixmap | None（背景折射源）
    bd_dpr: float = 1.0
    bd_off: object = None   # QPointF | None
    body_shadow_rect: QRectF = field(default=None)


def has_backdrop(ctx: "CapCtx") -> bool:
    return ctx.bd is not None and ctx.trans > 0.02


def paint_selected_glow(p, ctx: CapCtx) -> None:
    """选中三层同心辉光。"""
    if not (ctx.selected and ctx.glass > 0.02):
        return
    rect, r, skin = ctx.rect, ctx.r, ctx.skin
    w, h = rect.width(), rect.height()
    for grow, a in ((0.05, 100), (0.11, 55), (0.20, 26)):
        gc = QColor(skin.accent)
        gc.setAlpha(int(a * ctx.glass * (0.55 + 0.45 * ctx.glass)))
        p.setPen(QPen(gc, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(-w * grow, -h * grow,
                                        w * grow, h * grow),
                          r + w * grow, r + h * grow)


def paint_shadow(p, ctx: CapCtx) -> None:
    """键帽投影（背景在场 ×0.6——黑影叠透字背景加重拖影观感，D-046）。"""
    rect, r = ctx.rect, ctx.r
    a = int(70 * (1.0 - ctx.glass * 0.55)
            * (0.6 if has_backdrop(ctx) else 1.0))
    p.setPen(NO_PEN)
    p.setBrush(QColor(0, 0, 0, a))
    p.drawRoundedRect(rect.translated(0, 2.6), r, r)


def paint_body(p, ctx: CapCtx) -> None:
    """帽体：选中 = accent 实色；非选中 = 透镜磨砂背景 + 染色渐变。"""
    import math
    rect, r, skin = ctx.rect, ctx.r, ctx.skin
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if ctx.selected:
        base = QColor(skin.accent)
        base.setAlpha(int(238 - 50 * ctx.trans))
        p.setPen(NO_PEN)
        p.setBrush(base)
        p.drawRoundedRect(rect, r, r)
        return
    if ctx.trans > 0.02 and ctx.bd is not None and ctx.bd_off is not None:
        # 圆角路径裁剪（D-043）+ 86% 透明度磨砂（D-048 去雾：透更多真桌面）
        p.save()
        rounded = QPainterPath()
        rounded.addRoundedRect(rect, r, r)
        p.setClipPath(rounded)
        p.setRenderHint(p.RenderHint.SmoothPixmapTransform, True)
        p.setOpacity(0.86)
        wx = x + ctx.bd_off.x()
        wy = y + ctx.bd_off.y()
        lens = 1.18
        sw, sh = w / lens, h / lens
        sx = (wx + w / 2 - sw / 2) * ctx.bd_dpr
        sy = (wy + h / 2 - sh / 2) * ctx.bd_dpr
        p.drawPixmap(QRectF(x, y, w, h), ctx.bd,
                     QRectF(sx, sy, sw * ctx.bd_dpr, sh * ctx.bd_dpr))
        p.setOpacity(1.0)
        p.restore()
    top = QColor(skin.cap_top)
    bot = QColor(skin.cap_bottom)
    a = int((255 - 160 * ctx.glass) * (1.0 - ctx.trans))
    if has_backdrop(ctx):
        a = int(a * 0.38)              # D-048 去雾：染色从 0.55 减到 0.38
    top.setAlpha(a)
    bot.setAlpha(a)
    grad = QLinearGradient(0, y, 0, y + h)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bot)
    p.setPen(NO_PEN)
    p.setBrush(grad)
    p.drawRoundedRect(rect, r, r)


def paint_sheen(p, ctx: CapCtx) -> None:
    """斜光带 + 顶部流光（随光源横/纵接近增减；背景在场减量）。"""
    rect, r = ctx.rect, ctx.r
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    bd_k = 0.55 if has_backdrop(ctx) else 1.0
    if ctx.glass > 0.02 and ctx.tex.sheen > 0.02:
        sheen_k = ctx.tex.sheen * (1.0 - ctx.trans * 0.45) * bd_k
        diag = QLinearGradient(x, y, x + w, y + h)
        diag.setColorAt(0.0, QColor(255, 255, 255, 0))
        diag.setColorAt(0.32, QColor(255, 255, 255,
                                     int(34 * ctx.glass * sheen_k)))
        diag.setColorAt(0.52, QColor(255, 255, 255, 0))
        diag.setColorAt(0.82, QColor(255, 255, 255,
                                     int(12 * ctx.glass * sheen_k)))
        diag.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(NO_PEN)
        p.setBrush(diag)
        p.drawRoundedRect(rect, r, r)
    if ctx.glass > 0.02:
        prox = 1.0
        if ctx.light is not None and ctx.tex.light_gain > 0.02:
            vy = max(-1.0, min(1.0, (ctx.light.y() - (y + h * 0.38))
                               / (1.6 * ctx.u)))
            px_ = max(0.0, 1.0 - abs(ctx.light.x() - ctx.cx0) / (4.0 * ctx.u))
            prox = 0.5 + (0.55 + 0.45 * max(0.0, -vy)) * px_ \
                * min(ctx.tex.light_gain, 1.0)
        hi_a = int((52 + (20 if ctx.selected else 0)) * ctx.glass * prox
                   * (0.45 if has_backdrop(ctx) else 1.0))   # D-048 去雾
        gl = QLinearGradient(0, y, 0, y + h * 0.6)
        gl.setColorAt(0.0, QColor(255, 255, 255, min(hi_a, 170)))
        gl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(NO_PEN)
        p.setBrush(gl)
        p.drawRoundedRect(rect.adjusted(r * 0.3, r * 0.25, -r * 0.3, -h * 0.40),
                          r * 0.85, r * 0.85)


def paint_depth(p, ctx: CapCtx) -> None:
    """内页厚度：底部内阴影 + 环境倒影带（背景在场 ×0.6 减雾）。"""
    if ctx.tex.depth <= 0.05:
        return
    rect, r = ctx.rect, ctx.r
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    dk = 0.6 if has_backdrop(ctx) else 1.0
    p.save()
    p.setClipRect(QRectF(x - 2, y + h * 0.72, w + 4, h * 0.4))
    p.setPen(QPen(QColor(10, 14, 24, int(70 * ctx.tex.depth * dk)), 2.0))
    p.setBrush(Qt.NoBrush)
    if ctx.body_shadow_rect is not None:
        p.drawRoundedRect(ctx.body_shadow_rect, r, r)
    p.restore()
    band_gain = 1.0
    if ctx.light is not None and ctx.tex.light_gain > 0.02:
        vy_b = (ctx.light.y() - (y + h * 0.5)) / (1.6 * ctx.u)
        band_gain = 0.6 + 0.7 * max(0.0, min(1.0, vy_b))
    band = QRectF(x + r * 0.4, y + h * 0.60, w - r * 0.8, h * 0.30)
    bg = QLinearGradient(band.x(), band.y(), band.x(), band.y() + band.height())
    bg.setColorAt(0.0, QColor(255, 255, 255, 0))
    bg.setColorAt(1.0, QColor(255, 255, 255,
                               int(30 * ctx.tex.depth * band_gain * dk)))
    p.setPen(NO_PEN)
    p.setBrush(bg)
    p.drawRoundedRect(band, r * 0.6, r * 0.6)


def paint_top_env_arcs(p, ctx: CapCtx) -> None:
    """三段边光：顶部白高光弧（clip 上半）+ 底部环境反光弧（clip 下半）。"""
    rect, r, skin = ctx.rect, ctx.r, ctx.skin
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    dk = 0.5 if has_backdrop(ctx) else 1.0        # D-048 去雾
    p.save()
    body = QRectF(x + 1, y + 1, w - 2, h - 2)
    top_a = int((40 + 110 * ctx.glass) * (1.25 if ctx.selected else 1.0) * dk)
    p.setClipRect(QRectF(x - 2, y - 2, w + 4, y - 2 + h * 0.52))
    p.setPen(QPen(QColor(255, 255, 255, min(top_a, 200)), 1.5))
    p.drawRoundedRect(body, r, r)
    p.setClipRect(QRectF(x - 2, y - 2 + h * 0.55, w + 4, h * 0.5 + 4))
    env = QColor(skin.cap_border).lighter(150)
    env.setAlpha(int((30 + 90 * ctx.glass) * (1.2 if ctx.selected else 1.0)
                     * dk))
    p.setPen(QPen(env, 1.3))
    p.drawRoundedRect(body, r, r)
    p.restore()


def paint_edges(p, ctx: CapCtx) -> None:
    """描边 + 密度环 + 光源照边（双层径向/切向羽化炫光）+ 色散 + 折射弧。"""
    import math
    rect, r, skin = ctx.rect, ctx.r, ctx.skin
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    bd_k = 1.0 if not has_backdrop(ctx) else 0.35     # D-048 去雾：密度环

    bc = QColor(skin.cap_border)
    bc.setAlpha(210)
    p.setPen(QPen(bc, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.7, 0.7, -0.7, -0.7), r, r)

    if ctx.trans > 0.02:
        dens = QColor(skin.cap_bottom)
        dens.setAlpha(int((46 * ctx.trans + 40 * ctx.glass) * bd_k))
        p.setPen(QPen(dens, 2.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(1.4, 1.4, -1.4, -1.4), r * 0.96,
                          r * 0.96)

    light = ctx.light
    tex = ctx.tex
    if light is not None and tex.light_gain > 0.02:
        nx = min(max(light.x(), x + r), x + w - r)
        ny = min(max(light.y(), y + r), y + h - r)
        near = QPointF(nx, ny)
        dist = math.hypot(light.x() - nx, light.y() - ny)
        gain = max(0.0, 1.0 - dist / (2.6 * ctx.u)) * min(tex.light_gain, 1.2)
        if gain > 0.03:
            la = int(205 * gain)
            lg = QRadialGradient(near, 2.2 * ctx.u)
            lg.setColorAt(0.0, QColor(255, 248, 226, min(la, 235)))
            lg.setColorAt(0.42, QColor(255, 240, 200, int(la * 0.42)))
            lg.setColorAt(1.0, QColor(255, 240, 200, 0))
            halo = QRadialGradient(near, 3.8 * ctx.u)
            halo.setColorAt(0.0, QColor(255, 244, 216, int(la * 0.34)))
            halo.setColorAt(0.55, QColor(255, 240, 200, int(la * 0.13)))
            halo.setColorAt(1.0, QColor(255, 240, 200, 0))
            p.setPen(QPen(QBrush(halo), 3.4))
            p.drawRoundedRect(rect, r, r)
            p.setPen(QPen(QBrush(lg), 2.0))
            p.drawRoundedRect(rect, r, r)
        if gain > 0.45:
            fa = int(190 * (gain - 0.45) / 0.55)
            if has_backdrop(ctx):
                fa = int(fa * 0.6)
            fl = 0.8 * ctx.u * gain

            def _streak(pen_w, gp, alpha):
                g2 = QLinearGradient(*gp)
                g2.setColorAt(0.0, QColor(255, 252, 240, 0))
                g2.setColorAt(0.5, QColor(255, 252, 240, alpha))
                g2.setColorAt(1.0, QColor(255, 252, 240, 0))
                return QPen(QBrush(g2), pen_w)

            d_l, d_r = abs(light.x() - x), abs(light.x() - (x + w))
            d_t, d_b = abs(light.y() - y), abs(light.y() - (y + h))
            if min(d_l, d_r) <= min(d_t, d_b):
                gx = x if d_l <= d_r else x + w
                for pen_w, ka in ((6.2, 0.16), (3.4, 0.42), (1.5, 1.0)):
                    gp = (0, ny - fl, 0, ny + fl)
                    p.setPen(_streak(pen_w, gp, int(fa * ka)))
                    p.drawLine(QPointF(gx, ny - fl), QPointF(gx, ny + fl))
            else:
                gy = y if d_t <= d_b else y + h
                for pen_w, ka in ((6.2, 0.16), (3.4, 0.42), (1.5, 1.0)):
                    gp = (nx - fl, 0, nx + fl, 0)
                    p.setPen(_streak(pen_w, gp, int(fa * ka)))
                    p.drawLine(QPointF(nx - fl, gy), QPointF(nx + fl, gy))

    if tex.dispersion > 0.05:
        da = int(64 * tex.dispersion)
        off = 0.9 * tex.dispersion
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(80, 220, 255, da), 1.0))
        p.drawRoundedRect(rect.adjusted(-off, -off, off, off), r, r)
        p.setPen(QPen(QColor(255, 96, 96, da), 1.0))
        p.drawRoundedRect(rect.adjusted(off, off, -off, -off), r, r)

    if tex.refract > 0.05:
        galpha = int(44 * tex.refract * (1.0 - ctx.trans * 0.4)
                     * (0.7 if has_backdrop(ctx) else 1.0))
        gbr = QLinearGradient(x, 0, x + w, 0)
        gbr.setColorAt(0.0, QColor(255, 255, 255, 0))
        gbr.setColorAt(0.28, QColor(255, 255, 255, int(galpha * 0.55)))
        gbr.setColorAt(0.52, QColor(255, 255, 255, galpha))
        gbr.setColorAt(0.78, QColor(255, 255, 255, int(galpha * 0.45)))
        gbr.setColorAt(1.0, QColor(255, 255, 255, 0))
        sag = 2.1 * tex.refract
        mid_y = y + h * 0.40
        path = QPainterPath(QPointF(x + r * 0.5, mid_y - sag * 0.5))
        path.quadTo(QPointF(ctx.cx0 + w * 0.04, mid_y + sag),
                    QPointF(x + w - r * 0.5, mid_y - sag * 0.5))
        p.setPen(QPen(QBrush(gbr), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if tex.depth > 0.3:
            path2 = QPainterPath(QPointF(x + r, y + h * 0.82))
            path2.quadTo(QPointF(ctx.cx0 - w * 0.05, y + h * 0.80),
                         QPointF(x + w - r, y + h * 0.84))
            p.setPen(QPen(QBrush(gbr), 1.0))
            p.drawPath(path2)
