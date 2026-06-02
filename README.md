# NativeLoopTimer

NativeLoopTimer 是一个面向 Windows 桌面环境的本地多任务定时器与闹钟工具。项目使用 Python、CustomTkinter、Windows Toast 通知、系统托盘和 Win32 电源事件监听实现，目标是提供一个轻量、可本地运行、对当前工作流干扰较少的提醒工具。

> 当前项目主要适配 Windows。Linux / macOS 未作为主要目标环境测试。

## 功能概览

- **多任务定时器**：支持同时创建多个倒计时任务，任务可独立暂停、继续、重置和删除。
- **闹钟提醒**：支持按指定时间提醒，并可配置重复日期。
- **自动循环**：倒计时触发后可选择自动进入下一轮。
- **Windows Toast 通知**：使用 Windows 原生通知展示提醒内容，尽量减少对当前窗口焦点的影响。
- **睡眠 / 唤醒处理**：监听 Windows 电源事件，系统从睡眠恢复后会检查并处理休眠期间错过的提醒。
- **系统托盘**：关闭主窗口后可保留托盘入口，支持显示窗口、暂停全部、恢复全部和退出。
- **迷你悬浮窗**：可切换到小窗模式，查看当前任务并进行暂停、重置、恢复主窗口等操作。
- **自定义提示音**：基于 Windows 本地音频能力播放提醒音，可在创建任务时选择铃声。
- **中英双语界面**：内置中文和英文文案，可在界面中切换。
- **任务排序与持久化**：支持任务拖拽排序，任务、语言等配置保存到本地 `config.json`。

## 适用场景

- 工作、学习或休息间隔提醒。
- 多个倒计时任务并行管理。
- 不希望提醒窗口频繁打断当前输入焦点的 Windows 用户。
- 想了解 Python 桌面应用、Windows Toast、系统托盘、Win32 事件监听和 PyInstaller 打包的开发者。

## 技术实现

项目主要由以下部分组成：

| 模块 | 说明 |
| --- | --- |
| `main.py` | 主程序入口，负责界面、任务管理、通知、托盘和配置持久化 |
| `backend.py` | 独立计时后端示例，使用 stdin / stdout JSON 与父进程通信 |
| `NativeLoopTimer.spec` | PyInstaller 打包配置 |
| `config.json` | 示例配置文件，实际运行时会优先使用用户配置目录中的配置 |
| `app_icon.ico` / `app_icon.png` | 应用图标资源 |

核心依赖：

- `customtkinter`：桌面 UI
- `pystray`：系统托盘
- `Pillow`：图标和图像处理
- `pywin32`：Win32 窗口和电源事件监听
- `winrt-Windows.UI.Notifications` / `winrt-Windows.Data.Xml.Dom`：Windows Toast 通知
- `winsound`：本地提示音播放

## 配置与数据

程序会优先把运行配置保存到：

```text
%APPDATA%\NativeLoopTimer\config.json
```

如果目录中存在旧版本地 `config.json`，程序会在首次运行时尝试迁移到用户配置目录。配置内容主要包括：

- 任务列表
- 倒计时时长或闹钟时间
- 暂停状态
- 自动循环状态
- 提示音路径
- 分组与排序
- 当前语言

## 快速运行

### 使用已打包版本

如果仓库 Releases 中提供了可执行文件：

1. 打开 [Releases](https://github.com/thisisfrankryan/NativeLoopTimer/releases)。
2. 下载 `NativeLoopTimer.exe`。
3. 双击运行。

### 从源码运行

```bash
git clone https://github.com/thisisfrankryan/NativeLoopTimer.git
cd NativeLoopTimer

pip install customtkinter pystray pillow pywin32 winrt-Windows.UI.Notifications winrt-Windows.Data.Xml.Dom
python main.py
```

建议使用 Python 3.10+，并在 Windows 环境中运行。

## 打包

项目包含 PyInstaller 配置文件，可用于生成单文件可执行程序：

```bash
pip install pyinstaller
pyinstaller NativeLoopTimer.spec --noconfirm
```

打包产物默认生成在 `dist/` 目录。

## 设计取舍

这个项目更关注本地桌面使用体验，因此做了一些取舍：

- 只重点适配 Windows，没有做跨平台抽象。
- 使用 Windows Toast 和 Win32 电源事件监听，换取更贴近系统的通知和唤醒处理。
- 配置使用本地 JSON 文件，结构简单，便于查看和迁移。
- 当前不是后台服务型应用，程序退出后不会继续计时。
- 睡眠期间错过的提醒会在唤醒后检查处理，不等同于系统级实时调度服务。

## 开发说明

仓库中可能包含本地构建目录或可执行文件，开发时更建议关注以下文件：

```text
main.py
backend.py
NativeLoopTimer.spec
config.json
app_icon.ico
app_icon.png
```

调试建议：

1. 先用 `python main.py` 运行源码。
2. 确认 Toast 通知、托盘、睡眠唤醒、配置保存等 Windows 相关能力正常。
3. 再使用 PyInstaller 打包。
4. 打包后在干净目录中运行 exe，确认配置路径、图标和通知行为正常。

## 后续可改进方向

- 增加设置页，统一管理通知、声音、开机启动和配置目录。
- 增加任务导入 / 导出。
- 增加更完整的异常日志文件，便于用户反馈问题。
- 增加自动化测试，覆盖时间计算、配置读写和任务状态变更。
- 清理构建产物，将源码、发布包和临时文件分得更清楚。

## License

本项目使用 [MIT License](LICENSE)。
