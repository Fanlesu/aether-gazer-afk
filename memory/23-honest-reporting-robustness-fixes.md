# 诚实上报 + 分辨率健壮性 + OCR 性能 统一修复 (2026-08-12/13)

代码审查发现的一批问题，按 P1-P5 优先级修复。**P1 已提交 (a09221d)，P2-P5 在 working tree 未提交。**

## P1 - 假成功上报 (commit a09221d ✅ 已提交)

4 处任务在不可达/取消时仍报 `success`，日志和 UI 误导用户：

| 文件 | 问题 | 修复 |
|------|------|------|
| `keyin_tasks.py` | 联合特勤扫荡体力不足取消后仍报成功 | `_confirm_and_dismiss` 返回 bool，取消时返回 `skipped: 体力不足，扫荡取消` |
| `activity_tasks.py` | 联防协议同样问题 | 同上 |
| `guild_tasks.py` | `data` 编造"已验证领取成功" | 改为诚实记录动作 `supply_clicked` / `task_clicked` |
| `duowei_tasks.py` | `_fight_battle` 无条件返回假 `won` | 返回 `None`，message 不再携带虚假战斗结果 |

配套修复：
- `daily_routine`: 子任务失败时上报 `failed` + 列出失败项名（不再掩盖为 success）
- 新增 `RedDotCheck` (`checks/red_dot.py`)，依赖新增的 `vision/color.py` 颜色检测；mail/observation 改用 Check，消除 Task 层直接用 vision 的 **L6 架构违规**
- `device.click`: post_click 驻留 `20ms->80ms`，修复 Unity 渲染帧读不到光标的偶发点击失效（详见用户级 memory [[click-timing-intermittent-failure]]）
- 测试: 统一 `asyncio.run` 修复 event loop 污染(19 假失败)、修 startup 过期坐标断言(4 真失败)、daily_routine 测试同步到 13 任务；**24 失败 -> 503 全绿**

## P2 - 分辨率健壮性 (working tree, 未提交)

截图高度封顶 720 但**不放大**，小窗口截图 <1280×720，硬编码 `/1280,/720` 会偏 ~20%。
- `duowei_tasks.py`: 新增 `_ocr_frac(ctx, r)` helper，用 `ctx.device.resolution` 实际尺寸换算，替换 11 处硬编码
- `activity_tasks.py`: `hy+50` 按截图高度缩放；`_H_SEARCH_REGION` / `_LEFT_COLUMN` 改 fractional
- `amusement_tasks.py`: `cy-49` / `+50` 按截图尺寸缩放
- `vision/ocr.py`: 新增 `_resolve_region()`，OCR region 支持 fractional 坐标（全 0~1 自动按图像缩放）— 基础设施，详见 [[10-resolution-agnostic-refactor]]

## P3 - OCR 性能统一 (working tree)

- `ocr_find` / `ocr_find_all` / `ocr_full` 全部改走 `ocr_once` 快路径（scale=0.7，~3x 提速）
- `FindTextCheck` 不再每次 ~3000ms
- 更新 `ocr.py` 顶部过时性能注释

## P4 - 死代码 / 失效文档 (working tree)

- `launcher.py`: `_run_scheduled` 改走 `HeadlessRunner`（无窗口后台跑），`retry_on_failure` 开关真正生效（旧实现开 GUI 自动启动，从不重试）
- `device.py`: 修正 InputGuard 误导注释（实际从未 `start`，光标锁定是 `click()` 内联 ClipCursor，非 WH_MOUSE_LL hook）

## P5 - 测试覆盖 (working tree)

- 新增 `test_observation_tasks.py`: 8 个测试覆盖红点门控（can_run True/False、无红点不按 G、有红点领日常）
- `test_shop_tasks.py` 补 `ClaimDailyStaminaPacks` 5 个测试
- 测试状态: **517 passed**（503 -> 517）

## 核心教训

1. **任务绝不能在未验证时返回 success 或编造 data** — 取消/失败必须如实报 skipped/failed（已补入 [[09-code-review-lessons]]）
2. **OCR 坐标换算必须用实际截图尺寸**，不能假设 1280×720（截图只缩不放）
3. **注释要如实** — InputGuard 声称"已启用 hook"但从未 start，会误导后续维护者

## 状态

- **创建**: 2026-08-13
- **P1**: 已提交 a09221d
- **P2-P5**: working tree 未提交，待 commit
