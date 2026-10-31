# IME 组合状态跨进程读取 spike 结果

- **A. ImmGetContext(跨进程)**：NULL（无效）
- **B. WM_GETTEXT**：无内容/无效
- **C. UIA Value/Text**：可读，len=0
- **C. UIA 组合中读 'zhong'**：✓ 含 zhong（COMPOSING 可判定）
- **C. UIA 确认后读**：✓ 拼音消失（ENDED 可判定）尾部='中'

结论：采用 C. UIA 作为组合状态读取通道；COMPOSING/ENDED 均可判定。
