# AetherGazer AFK — 深空之眼自动日常工具

[![Release](https://img.shields.io/github/v/release/Fanlesu/aether-gazer-afk?style=flat-square)](https://github.com/Fanlesu/aether-gazer-afk/releases/latest)
[![License: GPL-3.0](https://img.shields.io/github/license/Fanlesu/aether-gazer-afk?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)

自动完成深空之眼每日任务：邮件、商店、体力、公会、游园街、联防协议等。
通过截图+图像识别操作游戏，后台运行，不抢焦点。
多数领取类任务带**智能红点门控**：无待领奖励时自动跳过，减少无效点击与空跑。

> 本项目 fork 自 [fxmoling/anime-game-afk](https://github.com/fxmoling/anime-game-afk)，当前 v0.5.0 维护并发布于 [Fanlesu/aether-gazer-afk](https://github.com/Fanlesu/aether-gazer-afk)。

---

## ✨ 功能特性

| 任务 | 说明 |
|------|------|
| 🎮 启动游戏 | 自动检测游戏路径、跳过开屏弹窗 |
| 📬 领取邮件 | 一键领取所有邮件 |
| 🛒 购买情报 | 每日商店情报碎片 |
| 🔋 领取体力包 | 吨吨值福利包（每日补给） |
| 🏪 商店免费体力 | 商店冷却剂/移转之辉 |
| 🔭 弥弥观测站 | 缩短回归 + 领取奖励 |
| 🏰 公会补给 | 矩阵补给 + 公会任务奖励 |
| 🎡 游园街日常 | 自动放置、投喂、领取、委托、游园任务 |
| ⚔️ 联防协议 | 自动扫荡 + 领取奖励 |
| 📋 每日周常任务 | 一键领取任务奖励 |
| 📝 对策协议 | 领取任务奖励 |
| 🎲 多维变量 | 自动重复挑战，累积积分（独立流程） |
| 🗡️ 联合特勤 | 自动扫荡刻印副本（消耗体力） |
| 🧲 介质攫取 | 自动挑战并领取奖励（消耗体力） |

### 🧩 自定义任务编排（用户可自己设计动作）

从 v0.5.0 起，日常执行不再是写死的程序流程，而是**可在界面里自行编排的工作流**：

- **勾选 + 排序**：在「任务」页勾选要执行的内置任务，用上下移按钮调整执行顺序。
- **每任务参数**：为每个任务单独配置超时（timeout）、重试次数（retry）、执行前/后等待时间（wait_before / wait_after）。
- **收尾动作**：全部任务完成后自动执行收尾动作（如退出游戏与工具）。
- **安全锁定（safe）**：关键任务带强制保护，编排时不可被误关，避免破坏核心闭环。
- **实时状态**：执行时界面实时显示当前步骤与进度。

编排结果以数据驱动的计划（plan）持久化，**全流程 id 向后兼容**，旧配置自动迁移。

---

## 📦 下载与使用

### 1. 下载

从 [Releases](https://github.com/Fanlesu/aether-gazer-afk/releases/latest) 页面下载最新版 `anime-game-afk.zip`。

### 2. 解压并运行

1. 解压到任意目录（建议英文路径，不要放在 C 盘 Program Files 下）
2. 双击 `anime-game-afk.exe`
3. 勾选要执行的任务，点击 **▶ 开始**

### 3. 系统要求

- **Windows 10 (1903+) / Windows 11**（需要 Edge / WebView2 Runtime，系统一般自带）
- [**Visual C++ Redistributable 2015-2022 (x64)**](https://aka.ms/vs/17/release/vc_redist.x64.exe) — **必装**
- **深空之眼 PC 版**，窗口化运行，推荐分辨率 1280×720 或 1920×1080（16:9）
- 操控模式选择「键盘」（非键鼠模式）
- 游戏窗口不要最小化（可以在后台，但不能最小化）

---

## ❓ 常见问题

**Q: 连接失败 / 找不到游戏窗口**
A: 确认游戏已启动且处于主界面。窗口标题应为 "AetherGazer"。

**Q: 任务执行失败**
A: 确保游戏处于主界面（大厅），不在战斗/加载中。查看日志页面了解详情。

**Q: 自动启动游戏找不到路径**
A: 在设置页面手动指定游戏 exe 路径，或确保桌面有游戏快捷方式。

**Q: 双击 exe 没有反应？**
A: 请先安装 [VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)。若仍无反应，用命令提示符进入解压目录运行 `anime-game-afk.exe` 查看报错信息。

**Q: 多维变量挑战传送门对不准？**
A: 确保游戏分辨率为 16:9（如 1920×1080），操控模式为「键盘」。如修改了战斗快捷键，请在工具设置页同步配置。

---

| 层 | 技术 |
|----|------|
| 核心 | Python 3.11 + [MaaFramework](https://github.com/MaaXYZ/MaaFramework) |
| 视觉 | OpenCV 模板匹配 + RapidOCR（DirectML 后端） |
| 门控 | RedDotCheck 红点识别（HSV 双段 + 连通域 blob 过滤） |
| 前端 | Vue 3 + Vite |
| 窗口 | pywebview + WebView2 |
| 打包 | PyInstaller |

---

## ⚠️ 已知限制

- **弥弥观测站** 暂未接入红点门控，无奖励时也会执行点击（后续版本将补齐）。
- **介质攫取 / 联防协议** 个别界面识别（如「震动」）偶发失败，失败时会等待或跳过，不影响其他任务。
- **无自动更新**：需手动到 Releases 页面下载新版替换。
- 坐标基于分数坐标（分辨率无关），但游戏大版本更新 UI 后可能需要重新校准。

## 👨‍💻 开发

```bash
# 克隆项目
git clone https://github.com/Fanlesu/aether-gazer-afk.git
cd anime-game-afk

# 安装 Python 依赖
pip install -e ".[dev]"

# 安装前端依赖并构建
cd frontend && npm install && npm run build && cd ..

# 运行测试
pytest tests/

# 启动开发模式
python launcher.py

# 构建发布版
pip install pyinstaller
python build.py --zip
```

### 🏗️ 架构概览（v0.5.0 重构要点）

v0.5.0 对内部逻辑做了较大重构，目标是让引擎更通用、更易扩展新游戏：

- **引擎与内容分离**：通用任务引擎 `WorkflowEngine` 位于 `engine/`，与游戏无关；深空之眼专属逻辑作为「内容包（content pack）」注册。切换/新增游戏只需提供新的内容包，无需改动引擎。
- **识别与执行解耦**：图像识别（OpenCV 模板匹配 + RapidOCR）与动作编排（数据驱动的计划 / 工作流）各自独立，红点门控统一收口于知识层。
- **流程 id 动态化**：默认流程 id 由后端 `get_settings` 下发，前端不再硬编码，便于后续按游戏扩展。
- **导入干净**：内容包改为延迟注册，消除 `engine → content_pack → 游戏模块` 的循环依赖。

### 发布流程

在本仓库推送版本标签即可触发 GitHub Actions 自动构建发版（构建 Windows 版 exe 并打包为 zip 上传到 Release）：

```bash
git tag v0.5.0
git push <你的仓库 remote> v0.5.0
```

GitHub Actions 会自动：构建前端 → 打包 exe（`python build.py --zip`）→ 创建 Release 并上传 `anime-game-afk.zip`。

---

## 📄 许可证

本项目使用 [GPL-3.0](LICENSE) 许可证。

本项目使用了以下开源组件，详见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)：
- [MaaFramework](https://github.com/MaaXYZ/MaaFramework) (LGPL-3.0)
- [OpenCV](https://github.com/opencv/opencv) (Apache-2.0)
- [Vue.js](https://github.com/vuejs/core) (MIT)
- 及其他 — 完整列表见第三方许可证文件

---

## ⚠️ 免责声明

本工具仅供学习交流使用。
仅通过截图 + 图像识别读取画面，通过模拟鼠标键盘操作游戏，不涉及抓包、协议分析或内存修改。
使用本工具产生的任何后果由用户自行承担。
