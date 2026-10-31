# spike_gpu_glass 结论（真桌面）

- PASS  G1 GL 上下文+shader 初始化
- PASS  G1b grabFramebuffer 有效
- PASS  G1c 圆角外 alpha=0
- PASS  G2a 键帽内被绘制(alpha>0)
- PASS  G2b 折射相位偏移(diff=262)
- PASS  G3 GL 帧均值 1.28ms / max 3.08ms
- PASS  G3 CPU 24帽透镜均值 0.19ms / max 1.09ms
- FAIL  G3 结论: GL 未更快（1.28 vs 0.19）

GL init err: None
GL avg/max: 1.284/3.081 ms
CPU avg/max: 0.186/1.091 ms
