# 🧠 AI 犯错与踩坑经验持久化知识库 (AI Failure & Troubleshooting Log)

> 💡 **开发者提示**：本文件是 `NativeLoopTimer` 开发生命周期中，AI 代理在架构、API 调用、平台限制、打包发布以及工具链使用中犯过的错误、踩过的坑及“血泪教训”的持久化知识库。
> **当未来的 AI 辅助编码代理遇到棘手问题、报错无法解决时，请强制检索并阅读本文档，以寻找精准的避坑方案和现成解药！**

---

## 目录
1. [CustomTkinter CTkScrollableFrame 属性失效错误](#1-customtkinter-ctkscrollableframe-属性失效错误)
2. [PyInstaller 打包程序的“源码-字节码”不一致陷阱](#2-pyinstaller-打包程序的源码-字节码不一致陷阱)
3. [Windows 原生 Toast 通知 (winrt) 报错与注册限制](#3-windows-原生-toast-通知-winrt-报错与注册限制)
4. [Windows 桌面端应用多开与重复托盘图标问题](#4-windows-桌面端应用多开与重复托盘图标问题)
5. [系统睡眠/休眠唤醒后的计时器挂起与漂移](#5-系统睡眠休眠唤醒后的计时器挂起与漂移)
6. [Windows PowerShell 命令行连写语法报错](#6-windows-powershell-命令行连写语法报错)
7. [Git 仓库根路径无缝平移与索引错乱灾难](#7-git-仓库根路径无缝平移与索引错乱灾难)

---

### 1. CustomTkinter CTkScrollableFrame 属性失效错误

* **🚨 错误现象 (Symptom)**：
  运行 `main.py` 时直接崩溃，抛出 AttributeError：
  `AttributeError: 'CTkScrollableFrame' object has no attribute '_canvas'`
* **🔍 根本原因 (Root Cause)**：
  在 `customtkinter` 框架的版本迭代中，为了规范命名，底层的 tkinter Canvas 对象的内部引用名从早期的 `_canvas` 被修改/规范化为了 `_parent_canvas`。直接调用旧属性会直接导致报错。
* **🛠️ 解决方案 (Solution)**：
  在绑定画布配置事件及动态计算滚动条边界时，必须使用 **`_parent_canvas`** 代替 `_canvas`：
  ```python
  # 绑定画布
  self.main_scroll_container._parent_canvas.bind("<Configure>", ...)
  
  # 获取画布
  canvas = self.main_scroll_container._parent_canvas
  ```

---

### 2. PyInstaller 打包程序的“源码-字节码”不一致陷阱

* **🚨 错误现象 (Symptom)**：
  代码已经在 `main.py` 里改成了正确的 `_parent_canvas`，但双击运行编译好的 `.exe` 依旧顽固地报 `_canvas` 找不到的错误，且报错 traceback 指向的代码行明明写着 `_parent_canvas`！
* **🔍 根本原因 (Root Cause)**：
  1. `.exe` 已经编译好，里面固化的是修改前的**老字节码**。
  2. 当旧字节码运行报错时，Python 的 traceback 模块为了打印错误行，会去**硬盘上实时读取当前的 `main.py` 物理文件**。
  3. 此时物理文件已经改成了最新版，因而 traceback 显示了新代码，而实际执行的还是老字节码，从而形成了极具迷惑性的“灵异事件”。
* **🛠️ 解决方案 (Solution)**：
  修改源码后，**必须强制重新编译打包**：
  ```powershell
  pyinstaller NativeLoopTimer.spec --noconfirm
  ```
  重新编译后，务必将 `dist/` 下最新的 `.exe` 复制并覆盖到你的日常运行路径下！

---

### 3. Windows 原生 Toast 通知 (winrt) 报错与注册限制

* **🚨 错误现象 (Symptom)**：
  调用原生 `winrt` 的 `ToastNotificationManager.create_toast_notifier()` 时，直接闪退或抛出：
  `OSError: [WinError -2147023728] Element not found` 或参数数量错误。
* **🔍 根本原因 (Root Cause)**：
  Windows 原生 Toast 通知系统要求发送通知的进程必须具有明确的 **AppUserModelID (AUMID)** 注册。如果进程是直接通过 Python 或没有在开始菜单/注册表注册的 `.exe` 启动，系统找不到该应用信息就会直接报错。
* **🛠️ 解决方案 (Solution)**：
  1. **注册表写入**：在 `HKCU\Software\Classes\AppUserModelId\<你的AppID>` 下创建注册表键，声明应用的 `DisplayName`。
  2. **进程声明**：使用 `ctypes` 在进程启动第一秒强制声明当前进程的 AUMID：
     ```python
     import ctypes
     ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YourAppID")
     ```
  3. **ID 创建**：使用 `create_toast_notifier_with_id(app_id)` 或使用无参版绑定前一步声明的进程。

---

### 4. Windows 桌面端应用多开与重复托盘图标问题

* **🚨 错误现象 (Symptom)**：
  用户手抖多次双击 `.exe` 文件，导致系统右下角托盘区瞬间冒出几十个一模一样的闹钟图标，进程管理器中出现大量堆积，耗电且无法统一状态。
* **🔍 根本原因 (Root Cause)**：
  应用程序缺乏“单实例互斥锁”机制，无法感知到同名进程已在后台运行。
* **🛠️ 解决方案 (Solution)**：
  使用**本地回路 TCP 端口锁**替代传统的临时文件锁（文件锁在程序崩溃时有残留无法释放的隐患）：
  1. 程序启动时，尝试绑定本地高端口（如 `49512`）。
  2. **若绑定成功**：说明是第一实例，启动后台监听线程，等待接收指令。
  3. **若绑定失败**：说明已有实例运行。此时**向前一个实例发送 `"show"` 信号**，随即主动退出。
  4. **前实例响应**：监听到信号后，安全调度主线程将已隐藏的 Tkinter 窗口 deiconify（还原）并强制置前，实现“唤醒已有实例”的完美交互。
  ```python
  # 核心拦截逻辑
  try:
      instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      instance_socket.bind(('127.0.0.1', 49512))
      instance_socket.listen(1)
  except socket.error:
      # 唤醒老实例并退出
      ...
  ```

---

### 5. 系统睡眠/休眠唤醒后的计时器挂起与漂移

* **🚨 错误现象 (Symptom)**：
  Windows 电脑合盖休眠，几个小时后醒来，定时器和闹钟处于“静止/假死”状态，休眠期间本该触发的会议或吃药提醒完全被漏掉。
* **🔍 根本原因 (Root Cause)**：
  操作系统休眠时，普通的 `while time.sleep(1)` 线程也会随之挂起。唤醒后，时间计数器与系统物理时间脱节，产生严重漂移，且没有任何补偿机制。
* **🛠️ 解决方案 (Solution)**：
  1. **主动电源监听**：在后台开辟轻量守护线程，注册 Windows 原生消息只读窗口，拦截 `WM_POWERBROADCAST` 电源状态消息。
  2. **唤醒捕获**：当捕捉到 `PBT_APMRESUMESUSPEND` (0x0007) 或 `PBT_APMRESUMEAUTOMATIC` (0x0012) 唤醒事件时，触发补偿回调。
  3. **延迟补偿计算**：遍历所有活动任务，若“当前物理时间”已超过“预定触发时间”，**立即毫秒级补发 Toast 通知**，绝不遗漏任何提醒，并重置下个计时周期。

---

### 6. Windows PowerShell 命令行连写语法报错

* **🚨 错误现象 (Symptom)**：
  在终端中执行如 `git add . && git commit` 时，PowerShell 直接报错：
  `&& is not a valid statement separator`（&& 不是有效的语句分隔符）。
* **🔍 根本原因 (Root Cause)**：
  在老版本的 Windows PowerShell（5.1 及以下默认自带版本）中，不支持 Linux/Bash 规范的 `&&` 逻辑与连写符。
* **🛠️ 解决方案 (Solution)**：
  在 PowerShell 环境中，必须使用 **`;`**（分号）作为命令的顺序连写分隔符：
  ```powershell
  git add . ; git commit -m "Your Message"
  ```

---

### 7. Git 仓库根路径无缝平移与索引错乱灾难

* **🚨 错误现象 (Symptom)**：
  将 `.git` 和 `.gitignore` 从工作区根目录平移进入 `NativeLoopTimer` 子目录下后，运行 `git status` 发生灾难性的一幕：所有老文件被标记为“全部删除 (deleted)”，所有新文件被标记为“全部未追踪 (untracked)”。
* **🔍 根本原因 (Root Cause)**：
  Git 仓库被物理移动后，其内部 `index` 缓存中记录的文件路径依旧带有老路径的前缀（即 `NativeLoopTimer/...`）。移入新目录后，这个前缀变成了相对路径，导致相对定位完全错乱。
* **🛠️ 解决方案 (Solution)**：
  不要慌张！利用 Git 的内容相似度算法进行**无损平移路径更新**：
  1. 切换终端路径至最新的 `.git` 所在目录。
  2. 运行 `git rm -r --cached .` —— **清空当前带错误前缀的旧索引缓存**。
  3. 运行 `git add .` —— **将当前路径下的所有文件重新索引**。
  4. 提交更改：`git commit -m "..."`。
  Git 内部算法会自动以 **100% 相似度** 判定该操作为“文件重命名/物理平移”，从而**完美无损地保留了此前所有的 commit 开发备份历史！**
