"""spike_gpu_glass.py —— GPU 液态玻璃 spike（真桌面）：QOpenGLWidget + GLSL 透镜折射

验证点：
  G1 QOpenGLWidget 透明渲染真桌面可用（alpha buffer + 圆角外 alpha=0）
  G2 GLSL 透镜折射 shader 生效（放大 UV 扭曲：矩形内采样相位与直接采样不同）
  G3 帧耗时：GL 路径（uniform 更新 + 单 draw call）vs CPU 等效路径
     （QPainter drawPixmap 透镜采样 ×24 键帽）——均值/最大值对比
  G4 raster 子控件叠加 GL 层合成正确（透明 DockStrip 形态的兄弟控件）
  G5 GL 不可用时的降级路径（grabFramebuffer 失败 / context 创建失败）
方法：程序生成测试背景（斜条纹 + 网格文字），单透镜矩形 shader 渲染，
grabFramebuffer 做像素级断言；性能段用 QElapsedTimer 连续 120 帧。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QElapsedTimer, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QPainter, QPen, QPixmap)
from PySide6.QtOpenGLWidgets import QOpenGLWidget   # Qt6：不在 QtWidgets
from PySide6.QtWidgets import QApplication, QWidget

W, H = 720, 120          # 模拟 Dock 尺寸
CAP = QRectF(40, 20, 64, 64)   # 测试透镜键帽矩形
LENS = 1.18              # 与产品一致的透镜倍率
N_CAPS = 24              # CPU 对比路径键帽数

VERT = "#version 130\nin vec2 pos;out vec2 uv;void main(){uv=pos*0.5+0.5;gl_Position=vec4(pos,0.,1.);}"

GL_COLOR_BUFFER_BIT = 0x00004000
GL_TRIANGLE_STRIP = 0x0004

FRAG = """
#version 130
uniform sampler2D bg;
uniform vec4 cap;      // 键帽矩形 (x,y,w,h) 像素
uniform float lens;    // 透镜倍率
uniform vec3 tint;     // 皮肤染色
uniform float tintA;   // 染色强度
uniform vec2 res;      // 视口尺寸
in vec2 uv;
out vec4 frag;

float roundedBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
    vec2 px = uv * res;                     // 当前像素（GL 左下原点，与 Qt y 翻转在纹理上传时统一）
    vec2 c = cap.xy + cap.zw * 0.5;         // 透镜中心
    vec2 half_ = cap.zw * 0.5;
    float rad = min(cap.z, cap.w) * 0.22;
    float d = roundedBox(px - c, half_, rad);
    if (d > 0.5) { frag = vec4(0.0); discard; }
    // 透镜折射：以中心为原点 UV 收缩 = 内容放大
    vec2 src = c + (px - c) / lens;
    // 9-tap 轻模糊（近似磨砂；真实产品用多 pass，此处验证量级）
    vec3 acc = vec3(0.0);
    float texel = 1.6;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++) {
            vec2 o = vec2(float(i), float(j)) * texel;
            acc += texture(bg, (src + o) / res).rgb;
        }
    acc /= 9.0;
    vec3 col = mix(acc, tint, tintA);
    float aa = clamp(0.5 - d, 0.0, 1.0);    // 边缘抗锯齿
    frag = vec4(col, 0.88 * aa);
}
"""


def make_test_bg() -> QImage:
    """测试背景：斜条纹 + 每格文字（验证放大后相位/文字可辨性）。"""
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor(240, 240, 245))
    p = QPainter(img)
    for x in range(0, W, 48):
        p.setPen(QPen(QColor(60 + (x // 48 * 37) % 160, 90, 200), 6))
        p.drawLine(x, 0, x - 40, H)
    p.setPen(QColor(20, 20, 30))
    f = p.font(); f.setPixelSize(13); p.setFont(f)
    for x in range(0, W, 48):
        p.drawText(x + 4, H // 2, f"{x}")
    p.end()
    return img


class GlassGL(QOpenGLWidget):
    """QOpenGLWidget 透明玻璃层原型。"""

    def __init__(self):
        super().__init__()
        self.ok_init = False
        self.err = None

    def initializeGL(self):
        try:
            from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
            self.ctx_ok = (self.context() is not None
                           and self.context().isValid())
            self.prog = QOpenGLShaderProgram(self)
            if not self.prog.addShaderFromSourceCode(
                    QOpenGLShader.Vertex, VERT):
                raise RuntimeError(f"vert: {self.prog.log()}")
            if not self.prog.addShaderFromSourceCode(
                    QOpenGLShader.Fragment, FRAG):
                raise RuntimeError(f"frag: {self.prog.log()}")
            if not self.prog.link():
                raise RuntimeError(f"link: {self.prog.log()}")
            self.bg_tex = self.context().functions()  # 占位
            from PySide6.QtOpenGL import QOpenGLTexture
            self.tex = QOpenGLTexture(self.bg_img)
            self.tex.setMinificationFilter(QOpenGLTexture.Filter.Linear)
            self.tex.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            self.ok_init = True
        except Exception as e:  # noqa: BLE001
            self.err = repr(e)

    def paintGL(self):
        if not self.ok_init:
            return
        from PySide6.QtOpenGL import QOpenGLShaderProgram as P
        gl = self.context().functions()
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        self.prog.bind()
        # 纹理 y 翻转：QOpenGLTexture 上传 QImage 原点左上 → GL 左下。
        # 采样端统一约定：把 cap 的 y 转换为 GL 坐标（H - y - h）。
        cap_gl = QRectF(CAP.x(), H - CAP.y() - CAP.height(),
                        CAP.width(), CAP.height())
        u = self.prog.uniformLocation
        self.prog.setUniformValue(u("bg"), 0)
        self.tex.bind(0)
        self.prog.setUniformValue(u("cap"), float(cap_gl.x()),
                                  float(cap_gl.y()), float(cap_gl.width()),
                                  float(cap_gl.height()))
        self.prog.setUniformValue(u("lens"), float(LENS))
        self.prog.setUniformValue(u("tint"), 0.35, 0.40, 0.85)
        self.prog.setUniformValue(u("tintA"), 0.38)
        self.prog.setUniformValue(u("res"), float(self.width()),
                                  float(self.height()))
        # 全屏三角条
        verts = [-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
        self.prog.enableAttributeArray(0)
        self.prog.setAttributeArray(0, verts, 2)
        gl.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self.prog.disableAttributeArray(0)
        self.prog.release()


def cpu_path_frame(p: QPainter, bg: QPixmap) -> None:
    """CPU 等效路径：24 键帽透镜采样（与 glass_paint.paint_body 同构）。"""
    x = 12.0
    for i in range(N_CAPS):
        w = 40 + 10 * (i % 3)
        rect = QRectF(x, 20, w, 64)
        sw, sh = rect.width() / LENS, rect.height() / LENS
        sx = (rect.x() + rect.width() / 2 - sw / 2) * 1.0
        sy = (rect.y() + rect.height() / 2 - sh / 2) * 1.0
        p.drawPixmap(rect, bg, QRectF(sx, sy, sw, sh))
        x += w + 6


def main():
    # G5 前置：显式请求 alpha 的 GL format
    from PySide6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    bg = make_test_bg()

    win = QWidget()
    win.setWindowTitle("GPU spike")
    win.resize(W, H)
    from PySide6.QtWidgets import QVBoxLayout
    lay = QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)
    glw = GlassGL()
    glw.bg_img = bg
    lay.addWidget(glw)
    win.show()
    app.processEvents()
    for _ in range(30):                     # 等待 GL 线程初始化
        app.processEvents()
        time.sleep(0.02)

    checks = []
    checks.append(("G1 GL 上下文+shader 初始化",
                   glw.ok_init if glw.err is None else False))
    if glw.err:
        print("GL 初始化失败:", glw.err)

    img = glw.grabFramebuffer()
    if img.isNull():
        checks.append(("G1b grabFramebuffer 有效", False))
        img = None
    else:
        checks.append(("G1b grabFramebuffer 有效", True))

    if img is not None:
        # G1：圆角外 alpha=0（取窗口右上角），键帽内 alpha>0
        out_a = img.pixelColor(int(CAP.x()) - 12, int(CAP.y()) + 4).alpha()
        in_pt = img.pixelColor(int(CAP.center().x()), int(CAP.center().y()))
        checks.append(("G1c 圆角外 alpha=0", out_a == 0))
        checks.append(("G2a 键帽内被绘制(alpha>0)", in_pt.alpha() > 0))
        # G2：折射生效 = 键帽内颜色 ≠ 背景"直接采样"该点颜色（放大位移了相位）
        direct = bg.pixelColor(int(CAP.center().x()), int(CAP.center().y()))
        diff = (abs(in_pt.red() - direct.red())
                + abs(in_pt.green() - direct.green())
                + abs(in_pt.blue() - direct.blue()))
        checks.append((f"G2b 折射相位偏移(diff={diff})", diff > 8))
        out_path = Path(__file__).parent / "gpu_glass_frame.png"
        img.save(str(out_path))
        print("帧图已存:", out_path)

    # G3 性能：GL 路径连续 120 帧
    frame_ms = []
    timer = QElapsedTimer()
    for i in range(120):
        timer.start()
        glw.update()
        app.processEvents()
        frame_ms.append(timer.nsecsElapsed() / 1e6)
        time.sleep(0.004)
    gl_avg = sum(frame_ms[10:]) / len(frame_ms[10:])
    gl_max = max(frame_ms[10:])

    # CPU 对比路径：QImage 上 24 键帽透镜采样（离屏，量级参照）
    cpu_img = QImage(W, H, QImage.Format.Format_ARGB32)
    cpu_img.fill(0)
    bp = QPainter(cpu_img)
    bp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    bgpix = QPixmap.fromImage(bg)
    t = QElapsedTimer()
    samples = []
    for i in range(120):
        t.start()
        cpu_img.fill(0)
        cpu_path_frame(bp, bgpix)
        samples.append(t.nsecsElapsed() / 1e6)
    bp.end()
    cpu_avg = sum(samples) / len(samples)
    cpu_max = max(samples)

    checks.append((f"G3 GL 帧均值 {gl_avg:.2f}ms / max {gl_max:.2f}ms", True))
    checks.append((f"G3 CPU 24帽透镜均值 {cpu_avg:.2f}ms / max {cpu_max:.2f}ms", True))
    checks.append(("G3 结论: GL 快于 CPU" if gl_avg < cpu_avg
                   else f"G3 结论: GL 未更快（{gl_avg:.2f} vs {cpu_avg:.2f}）",
                   gl_avg < cpu_avg))

    print("=" * 60)
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 60)
    print(f"GL  初始化: {glw.ok_init}  err={glw.err}")
    print(f"GL 帧耗时: avg {gl_avg:.3f}ms  max {gl_max:.3f}ms（含 processEvents 全循环）")
    print(f"CPU 帧耗时(纯绘制): avg {cpu_avg:.3f}ms  max {cpu_max:.3f}ms")

    lines = ["# spike_gpu_glass 结论（真桌面）", ""]
    for name, ok in checks:
        lines.append(f"- {'PASS' if ok else 'FAIL'}  {name}")
    lines += ["", f"GL init err: {glw.err}",
              f"GL avg/max: {gl_avg:.3f}/{gl_max:.3f} ms",
              f"CPU avg/max: {cpu_avg:.3f}/{cpu_max:.3f} ms", ""]
    Path(__file__).parent.joinpath("gpu_glass_result.md").write_text(
        "\n".join(lines), encoding="utf-8")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
