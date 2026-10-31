# spike_global_hook 结论（真桌面）

- PASS  V1a 窗内左键投递
- PASS  V1b 窗内滚轮投递
- PASS  V1c 窗内右键投递
- PASS  V2 窗外零投递（滚轮）
- PASS  V3 Ctrl+Alt+M toggle
- PASS  V4 槽均在主线程执行
- PASS  V5 DoesNotAcceptFocus 点击不切前台

语义事件序列: ['LEFT', 'SCROLL_UP', 'RIGHT', 'TOGGLE']
原始观测: ['click:left@(853,918) inside=True', 'scroll:up@(853,918) inside=True', 'click:right@(853,918) inside=True', 'scroll:up@(503,728) inside=False']
语义: 解释但不吞（不改系统事件流）
