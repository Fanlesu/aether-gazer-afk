# Tray Icon 幽灵按钮残留 — 诊断与修复 (2026-08-14)

## 问题现象
GUI 运行一次后关闭，任务栏残留一个"无法关闭"的图标。历次修复（b246c3e、a318071）均未根除。

## 关键诊断（实测证据，推翻旧假设）
1. 关闭后主进程 `anime-game-afk.exe` / `python.exe` 均已退出（tasklist 确认）
2. 残留的 msedgewebview2.exe 全是系统组件（SearchHost=Windows搜索、MSPCManager=微软电脑管家）的，**无一属于我们**
3. 纯 pywebview 最小复现（`.tmp/min_close_test.py` 用 destroy、`.tmp/wm_close_test.py` 用 WM_CLOSE 模拟点✕）关闭后**均无残留**
4. **结论：残留不是进程，是 Windows 幽灵任务栏按钮。元凶是 `os._exit()` 强杀——在 closing 线程抢在窗口 WM_DESTROY 前杀进程，任务栏按钮来不及注销**

## 修复演进（三层）
- `b246c3e`: post-webview.start 改回异步 `_start_shutdown_thread`
- `a318071`: daemon 线程主动 `os._exit(0)`（**错误方向，制造幽灵按钮**）
- **当前未提交**: 移除无条件 `os._exit` 强杀 → 优雅退出；closing 后加 15s 兜底 Timer（仅 webview.start() 真挂死才强杀）；移除每次关闭 `taskkill /IM msedgewebview2.exe`（会误杀 SearchHost/MSPCManager 的 webview2）

## 当前状态（2026-08-14）
- [app.py](src/anime_game_afk/ui/app.py) 有**未提交**的优雅退出修复，已打包 `dist/anime-game-afk` 验证
- **新版关闭后无新残留 ✅**（用户实测确认，含 `webview.start() returned — exiting normally` 日志）
- 任务栏剩**最初一次**旧版强杀留下的幽灵按钮，待重启 explorer 清理

## 待办
- 提交 app.py 优雅退出修复（当前 HEAD 之后有未提交改动）
- 用户重启 Windows 资源管理器清旧幽灵按钮，确认任务栏干净
- 验证通过后更新本 memory

## 教训
- 任务栏残留 ≠ 进程残留：先查 tasklist + 进程父链，再下结论
- `os._exit` / `taskkill /IM` 是无差别强杀，正常关闭路径禁用（os._exit 留幽灵按钮、taskkill 误杀系统组件）
- 最小复现（纯 pywebview）能快速隔离"库 bug" vs "自身代码"
- pywebview 6.2.1 WinForms 后端：`on_close` 里 chromium 走 `hide()` + `Application.Exit()`，窗口关闭本身是干净的
