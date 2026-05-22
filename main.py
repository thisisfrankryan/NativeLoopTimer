import os
import sys
import time
import threading
import winreg
import ctypes
import json
import uuid
import re
import winsound
from PIL import Image, ImageDraw
import pystray
import customtkinter as ctk
import tkinter as tk

try:
    import pywinstyles
except ImportError:
    pywinstyles = None


# Import Windows Runtime notification APIs
import winrt.windows.ui.notifications as win_notify
import winrt.windows.data.xml.dom as win_xml

# Import Windows GUI/Power API bindings for sleep/wake monitoring
import win32gui
import win32con

def calculate_next_alarm(alarm_time_str, repeat_days):
    """
    Computes the exact Epoch timestamp for the next alarm trigger.
    alarm_time_str: "HH:MM" (e.g. "08:30")
    repeat_days: list of ints [1..7] representing ISO weekdays (1 = Monday, 7 = Sunday).
                 Empty list represents a single (one-off) alarm.
    """
    import datetime
    now = datetime.datetime.now()
    h, m = map(int, alarm_time_str.split(":"))
    
    # Target datetime today
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    
    if not repeat_days:
        # One-off alarm. If it already passed today, schedule for tomorrow.
        if target <= now:
            target += datetime.timedelta(days=1)
        return target.timestamp()
    else:
        # Recurring alarm. Find the next matching weekday (including today if target is in the future).
        for offset in range(8):
            candidate = target + datetime.timedelta(days=offset)
            cand_weekday = candidate.isoweekday()
            if cand_weekday in repeat_days:
                if candidate > now:
                    return candidate.timestamp()
        # Fallback
        return (target + datetime.timedelta(days=1)).timestamp()


class PowerMonitor:
    """
    Listens to native Windows power events (sleep/wake) using a lightweight
    message-only window in a dedicated background thread.
    """
    def __init__(self, on_resume_callback):
        self.on_resume_callback = on_resume_callback
        self.hwnd = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="PowerMonitorThread")
        self.thread.start()

    def _run(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self.wnd_proc
        wc.lpszClassName = "NativeLoopTimerPowerMonitor"
        wc.hInstance = win32gui.GetModuleHandle(None)
        
        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = wc.lpszClassName
            
        self.hwnd = win32gui.CreateWindowEx(
            0,
            class_atom,
            "PowerMonitorWindow",
            0, 0, 0, 0, 0,
            win32con.HWND_MESSAGE,
            0,
            wc.hInstance,
            None
        )
        
        win32gui.PumpMessages()

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_POWERBROADCAST:
            # PBT_APMRESUMESUSPEND = 0x0007, PBT_APMRESUMEAUTOMATIC = 0x0012
            if wparam in (0x0007, 0x0012):
                print("[PowerMonitor] System wake-up event detected!")
                self.on_resume_callback()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class CTkCircularTimer(tk.Canvas):
    def __init__(self, parent, size=280, bg_color="#1E293B", color="#10B981"):
        super().__init__(parent, width=size, height=size, bg=bg_color, highlightthickness=0)
        self.size = size
        self.color = color
        self.ratio = 1.0
        self.is_paused = False
        self.time_str = "00:00"
        self.bg_color = bg_color
        self.draw()

    def set_progress(self, ratio, is_paused=False, color=None, time_str="00:00"):
        self.ratio = max(0.0, min(1.0, ratio))
        self.is_paused = is_paused
        if color:
            self.color = color
        self.time_str = time_str
        self.draw()

    def draw(self):
        self.delete("all")
        s = self.size
        cx = s / 2
        cy = s / 2
        
        # Radii definitions
        outer_r = (s / 2) - 15  # Outer border ring radius
        inner_max_r = outer_r - 10  # Max radius of the shrinking solid circle
        
        # Define high-end soft dual-tone color mapping
        # Green: ring #10B981, shrinking circle #064E3B
        # Yellow: ring #F59E0B, shrinking circle #78350F
        # Red: ring #EF4444, shrinking circle #7F1D1D
        ring_color = self.color
        if self.color == "#10B981": # Green
            fill_color = "#064E3B"
        elif self.color == "#F59E0B": # Yellow
            fill_color = "#78350F"
        elif self.color == "#EF4444": # Red
            fill_color = "#7F1D1D"
        else:
            fill_color = "#1E3A8A" # Fallback deep blue
            
        # 1. Draw outer background ring track (slate gray)
        self.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, 
                         outline="#334155", width=4)
                         
        # 2. Draw active progress circular arc (winding down from 360 to 0 degrees)
        extent = -360.0 * self.ratio
        if extent != 0:
            self.create_arc(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                            start=90, extent=extent, style="arc", outline=ring_color, width=6)
                            
        # 3. Draw the shrinking solid inner circle (radius is proportional to self.ratio)
        if self.ratio > 0.0:
            inner_r = inner_max_r * self.ratio
            self.create_oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
                             fill=fill_color, outline="")
                             
        # 4. Draw the centered countdown time text
        font_size = int(s * 0.12)
        self.create_text(cx, cy, text=self.time_str, fill="#FFFFFF", 
                         font=("Segoe UI", font_size, "bold"))


class CTkAlarmClock(tk.Canvas):
    def __init__(self, parent, size=28, bg_color="#1E293B", clock_color="#10B981"):
        super().__init__(parent, width=size, height=size, bg=bg_color, highlightthickness=0)
        self.size = size
        self.clock_color = clock_color
        self.is_paused = False
        self.draw()

    def set_progress(self, ratio, is_paused=False, color=None):
        self.is_paused = is_paused
        if color:
            self.clock_color = color
        self.draw()

    def draw(self):
        import math
        self.delete("all")
        s = self.size
        cx = s / 2
        cy = s / 2
        r = (s / 2) - max(4.0, s * 0.1)
        
        # Alarm feet
        self.create_line(cx - r + max(2.0, s * 0.06), cy + r - max(1.0, s * 0.03), cx - r - max(1.0, s * 0.03), cy + r + max(2.0, s * 0.06), fill="#64748B", width=max(2.0, s * 0.06))
        self.create_line(cx + r - max(2.0, s * 0.06), cy + r - max(1.0, s * 0.03), cx + r + max(1.0, s * 0.03), cy + r + max(2.0, s * 0.06), fill="#64748B", width=max(2.0, s * 0.06))
        
        # Twin bells at top
        bell_r = max(2.0, s * 0.1)
        self.create_oval(cx - r - bell_r, cy - r - bell_r, cx - r + bell_r, cy - r + bell_r, fill="#64748B", outline="")
        self.create_oval(cx + r - bell_r, cy - r - bell_r, cx + r + bell_r, cy - r + bell_r, fill="#64748B", outline="")
        
        # Outer clock face ring
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#64748B", width=max(1.5, s * 0.05))
        
        # Clock hands at 10:10
        hx = cx + (r * 0.45) * math.cos(math.radians(-120))
        hy = cy + (r * 0.45) * math.sin(math.radians(-120))
        self.create_line(cx, cy, hx, hy, fill=self.clock_color, width=max(1.5, s * 0.05), capstyle="round")
        
        mx = cx + (r * 0.65) * math.cos(math.radians(-30))
        my = cy + (r * 0.65) * math.sin(math.radians(-30))
        self.create_line(cx, cy, mx, my, fill=self.clock_color, width=max(1.2, s * 0.04), capstyle="round")
        
        # Center pin dot
        pin_r = max(1.0, s * 0.04)
        self.create_oval(cx - pin_r, cy - pin_r, cx + pin_r, cy + pin_r, fill=self.clock_color, outline="")


class PiPWindow(ctk.CTkToplevel):
    def __init__(self, parent_app):
        super().__init__(parent_app.root)
        self.app = parent_app
        
        # Window setup
        self.title(self.app.loc[self.app.current_lang].get("pip_title", "PiP Mode"))
        self.overrideredirect(True) # Borderless
        self.attributes("-topmost", True) # Always on top
        self.attributes("-alpha", 0.85) # Transparent
        
        # Background color matching our dark aesthetic
        self.configure(fg_color="#1E293B")
        
        # Apply Apple-like Frosted Glass "Liquid Glass" theme to PiP window if pywinstyles is available
        if pywinstyles:
            try:
                pywinstyles.apply_style(self, "acrylic")
            except Exception:
                pass
        
        # Position in bottom-right corner of screen
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = screen_width - 220
        y = screen_height - 120
        self.geometry(f"200x70+{x}+{y}")
        
        # Drag bindings
        self._drag_data = (0, 0)
        self.bind("<Button-1>", self.start_drag)
        self.bind("<B1-Motion>", self.on_drag)
        
        # Main layout frame
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=8, pady=6)
        
        # Top half: Task name & Icon
        self.task_label = ctk.CTkLabel(
            self.content_frame, 
            text=self.app.loc[self.app.current_lang].get("pip_no_task", "No active task"), 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#E5E7EB",
            anchor="w"
        )
        self.task_label.pack(side="top", anchor="w", fill="x")
        
        # Bottom half: Timer countdown and Controls row
        self.bottom_row = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.bottom_row.pack(side="top", fill="x", pady=(2, 0))
        
        self.time_label = ctk.CTkLabel(
            self.bottom_row,
            text="00:00",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#10B981",
            anchor="w"
        )
        self.time_label.pack(side="left", anchor="w")
        
        # Action buttons on the right side of the bottom row
        btn_frame = ctk.CTkFrame(self.bottom_row, fg_color="transparent")
        btn_frame.pack(side="right", fill="y")
        
        self.play_btn = ctk.CTkButton(
            btn_frame,
            text="⏸",
            width=22,
            height=22,
            fg_color="#374151",
            hover_color="#4B5563",
            corner_radius=4,
            font=("Segoe UI", 10),
            command=self.toggle_active_task
        )
        self.play_btn.pack(side="left", padx=2)
        
        self.reset_btn = ctk.CTkButton(
            btn_frame,
            text="🔄",
            width=22,
            height=22,
            fg_color="#374151",
            hover_color="#4B5563",
            corner_radius=4,
            font=("Segoe UI", 10),
            command=self.reset_active_task
        )
        self.reset_btn.pack(side="left", padx=2)
        
        self.unpin_btn = ctk.CTkButton(
            btn_frame,
            text="↩",
            width=22,
            height=22,
            fg_color="#374151",
            hover_color="#60A5FA",
            text_color="#60A5FA",
            corner_radius=4,
            font=("Segoe UI", 10, "bold"),
            command=self.close_pip
        )
        self.unpin_btn.pack(side="left", padx=2)
        
        # Start update cycle
        self.update_pip()

    def start_drag(self, event):
        self._drag_data = (event.x_root, event.y_root)
        
    def on_drag(self, event):
        delta_x = event.x_root - self._drag_data[0]
        delta_y = event.y_root - self._drag_data[1]
        x = self.winfo_x() + delta_x
        y = self.winfo_y() + delta_y
        self.geometry(f"+{x}+{y}")
        self._drag_data = (event.x_root, event.y_root)

    def get_active_task(self):
        with self.app.lock:
            if not self.app.tasks:
                return None
            for t in self.app.tasks:
                if t["type"] == "timer" and not t["is_paused"]:
                    return t
            for t in self.app.tasks:
                if t["type"] == "alarm" and not t["is_paused"]:
                    return t
            for t in self.app.tasks:
                if t["type"] == "timer" and t["is_paused"]:
                    return t
            for t in self.app.tasks:
                if t["type"] == "alarm" and t["is_paused"]:
                    return t
            return self.app.tasks[0]

    def update_pip(self):
        if not self.winfo_exists():
            return
            
        task = self.get_active_task()
        lang = self.app.current_lang
        
        if not task:
            self.task_label.configure(text=self.app.loc[lang]["empty_list"][:18])
            self.time_label.configure(text="--:--", text_color="#9CA3AF")
            self.play_btn.configure(state="disabled")
            self.reset_btn.configure(state="disabled")
        else:
            self.play_btn.configure(state="normal")
            self.reset_btn.configure(state="normal")
            
            icon = "⏳" if task["type"] == "timer" else "⏰"
            name = task["name"]
            if len(name) > 10:
                name = name[:8] + "..."
            self.task_label.configure(text=f"{icon} {name}")
            
            btn_text = "⏸" if not task["is_paused"] else "▶"
            btn_fg = "#374151" if not task["is_paused"] else "#10B981"
            self.play_btn.configure(text=btn_text, fg_color=btn_fg)
            
            curr = time.time()
            if task["is_paused"]:
                if task["type"] == "timer":
                    rem = task["remaining_seconds"]
                    rem_min = int(rem // 60)
                    rem_sec = int(rem % 60)
                    self.time_label.configure(text=f"{rem_min:02d}:{rem_sec:02d}", text_color="#F59E0B")
                else:
                    self.time_label.configure(text=self.app.loc[lang]["status_paused"][:6], text_color="#F59E0B")
            else:
                if task["type"] == "timer":
                    remaining = task["target_time"] - curr
                    if remaining < 0:
                        remaining = 0
                    rem_min = int(remaining // 60)
                    rem_sec = int(remaining % 60)
                    self.time_label.configure(text=f"{rem_min:02d}:{rem_sec:02d}", text_color="#10B981" if remaining >= 60.0 else "#EF4444")
                else:
                    self.time_label.configure(text=task["alarm_time"], text_color="#10B981")
                    
        self.after(500, self.update_pip)

    def toggle_active_task(self):
        task = self.get_active_task()
        if task:
            self.app.toggle_task(task["id"])
            
    def reset_active_task(self):
        task = self.get_active_task()
        if task:
            self.app.reset_task(task["id"])
            
    def close_pip(self):
        self.app.pip_window = None
        self.destroy()
        self.app.show_window()


class TimerApp:
    def __init__(self):
        # Default state
        self.tasks = []
        self.is_running = True
        self.timer_thread = None
        self.status_loop_active = False
        self.lock = threading.Lock()
        
        self.root = None
        self.tray_icon = None
        
        # UI task tracking to update text in real-time without flickering
        self.task_labels = {}
        self.task_status_badges = {}
        self.task_progress_bars = {}
        self.task_hourglasses = {}
        self.task_card_widgets = {}
        self.pip_window = None
        
        # Paths
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
        self.ico_path = os.path.join(self.app_dir, "app_icon.ico")
        self.png_path = os.path.join(self.app_dir, "app_icon.png")
        
        # Localization data
        self.loc = {
            "zh": {
                "title": "⏰ 多任务原生定时中心",
                "subtitle": "独立多任务并发 · 暂停/恢复管理 · 系统级防丢自唤醒",
                "tab_timer": "⏳ 定时器",
                "tab_alarm": "⏰ 闹钟",
                "timer_duration": "倒计时时间 (分钟):",
                "timer_placeholder": "输入分钟数 (如 20 或 0.5)",
                "timer_loop": "触发后自动循环计时",
                "alarm_time": "闹钟时间:",
                "alarm_hour_placeholder": "时",
                "alarm_minute_placeholder": "分",
                "repeat_cycle": "重复周期 (不勾选为单次):",
                "everyday": "每天 (一至日)",
                "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
                "msg_label": "提醒显示内容:",
                "msg_placeholder": "输入 Toast 通知要显示的文本内容",
                "msg_default": "时间到了！请起来活动一下，喝杯水休息一会吧！",
                "add_task": "➕ 添加并启动新任务",
                "add_task_short": "➕ 启动",
                "pause_all": "⏸ 暂停全部",
                "resume_all": "▶ 恢复全部",
                "list_title": "⏳ 当前活动任务与闹钟列表",
                "empty_list": "暂无运行中的定时任务，请在上方添加！",
                "error_msg_empty": "❌ 请输入提醒内容！",
                "sound_label": "🔔 响铃提示音选择:",
                "error_timer_invalid": "❌ 循环时间必须是大于 0 的数字！",
                "error_alarm_invalid": "❌ 闹钟时间格式无效！在小时 and 分钟框输入数字即可！",
                "success_add": "✓ 任务添加并启动成功！",
                "status_waiting": "等待中...",
                "status_paused": "已暂停",
                "status_paused_rem": "暂停 (余 {min}分{sec}秒)",
                "status_rem": "剩余: {min}分{sec}秒",
                "status_target": "目标: {time}{repeat}",
                "repeat_everyday": " (每天)",
                "repeat_weekdays": " (工作日)",
                "repeat_weekends": " (周末)",
                "repeat_days_fmt": " (周{days})",
                "repeat_oneoff": " (单次)",
                "toast_title_single": "定时中心提醒",
                "toast_title_multi": "错过了 {count} 个提醒",
                "tray_show": "显示设置 (Settings)",
                "tray_pause": "全局暂停所有 (Pause All)",
                "tray_resume": "全局恢复所有 (Resume All)",
                "tray_exit": "退出 (Exit)",
                "tray_title": "多任务原生定时中心",
                "pip_title": "画中画模式",
                "pip_no_task": "暂无活动任务",
                "edit_task_title": "编辑任务设置",
                "edit_task_header": "✏️ 修改任务配置",
                "dialog_cancel": "取消",
                "dialog_save": "保存"
            },
            "en": {
                "title": "⏰ Multi-Task Native Timer Center",
                "subtitle": "Independent Concurrency · Pause/Resume Management · Wake-up Protection",
                "tab_timer": "⏳ Timer",
                "tab_alarm": "⏰ Alarm",
                "timer_duration": "Countdown Duration (Minutes):",
                "timer_placeholder": "Enter minutes (e.g. 20 or 0.5)",
                "timer_loop": "Auto-loop timing after trigger",
                "alarm_time": "Alarm Time:",
                "alarm_hour_placeholder": "Hr",
                "alarm_minute_placeholder": "Min",
                "repeat_cycle": "Repeat Cycle (One-off if unchecked):",
                "everyday": "Everyday (Mon-Sun)",
                "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "msg_label": "Alert Message Content:",
                "msg_placeholder": "Enter text to display in Toast notification",
                "msg_default": "Time's up! Please get up, stretch, drink some water and take a break!",
                "add_task": "➕ Add and Start New Task",
                "add_task_short": "➕ Start",
                "pause_all": "⏸ Pause All",
                "resume_all": "▶ Resume All",
                "list_title": "⏳ Active Tasks & Alarms List",
                "empty_list": "No active tasks. Add a new one above!",
                "error_msg_empty": "❌ Please enter the alert message!",
                "sound_label": "🔔 Alert Sound Selector:",
                "error_timer_invalid": "❌ Countdown duration must be a number greater than 0!",
                "error_alarm_invalid": "❌ Invalid alarm time format! Just enter numbers in the hour and minute boxes!",
                "success_add": "✓ Task added and started successfully!",
                "status_waiting": "Waiting...",
                "status_paused": "Paused",
                "status_paused_rem": "Paused ({min}m {sec}s left)",
                "status_rem": "Remaining: {min}m {sec}s",
                "status_target": "Target: {time}{repeat}",
                "repeat_everyday": " (Everyday)",
                "repeat_weekdays": " (Weekdays)",
                "repeat_weekends": " (Weekends)",
                "repeat_days_fmt": " ({days})",
                "repeat_oneoff": " (One-off)",
                "toast_title_single": "Timer Center Reminder",
                "toast_title_multi": "Missed {count} reminders",
                "tray_show": "Show Settings",
                "tray_pause": "Pause All Tasks",
                "tray_resume": "Resume All Tasks",
                "tray_exit": "Exit",
                "tray_title": "Multi-Task Native Timer Center",
                "pip_title": "PiP Mode",
                "pip_no_task": "No active task",
                "edit_task_title": "Edit Task Settings",
                "edit_task_header": "✏️ Edit Task Configuration",
                "dialog_cancel": "Cancel",
                "dialog_save": "Save"
            }
        }
        self.current_lang = "zh"
        
        # Bilingual sound selections mapped to high-quality Windows pre-installed media chimes
        self.sound_options = {
            "zh": {
                "🔔 经典闹铃 (Classic Alarm)": "C:/Windows/Media/Alarm01.wav",
                "🔔 晨光风铃 (Morning Chimes)": "C:/Windows/Media/chimes.wav",
                "🔔 静谧和弦 (Serene Chord)": "C:/Windows/Media/chord.wav",
                "🔔 温馨叮咚 (Warm Ding)": "C:/Windows/Media/ding.wav",
                "🔔 凯旋之声 (Tada Fanfare)": "C:/Windows/Media/tada.wav",
                "🔔 电子警报 (Digital Alarm)": "C:/Windows/Media/Alarm03.wav",
                "🔔 系统默认 (System Default)": "C:/Windows/Media/Windows Default.wav"
            },
            "en": {
                "🔔 Classic Alarm": "C:/Windows/Media/Alarm01.wav",
                "🔔 Morning Chimes": "C:/Windows/Media/chimes.wav",
                "🔔 Serene Chord": "C:/Windows/Media/chord.wav",
                "🔔 Warm Ding": "C:/Windows/Media/ding.wav",
                "🔔 Tada Fanfare": "C:/Windows/Media/tada.wav",
                "🔔 Digital Alarm": "C:/Windows/Media/Alarm03.wav",
                "🔔 System Default": "C:/Windows/Media/Windows Default.wav"
            }
        }
        
        # Initialize
        self.app_id = "NativeLoopTimer"
        self.register_app_id()
        self.ensure_assets()
        
        # Load tasks and language choice from config.json
        self.tasks = self.load_config()
        self.check_and_compensate_missed_tasks(time.time())
        
        # Start power monitor
        self.power_monitor = PowerMonitor(self.on_system_wake)
        
        # Start timer scheduler thread
        self.timer_thread = threading.Thread(target=self.timer_loop, daemon=True, name="SchedulerThread")
        self.timer_thread.start()

    def register_app_id(self):
        """Register the application under HKCU to authorize Toast notifications."""
        path = rf"Software\Classes\AppUserModelId\{self.app_id}"
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "多任务原生定时中心 (NativeLoopTimer)")
            winreg.CloseKey(key)
            
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(self.app_id)
            print("[TimerApp] AppUserModelID successfully registered.")
        except Exception as e:
            print(f"[TimerApp] Warning registering AUMID: {e}")

    def ensure_assets(self):
        """Programmatically generate a beautiful, modern multi-resolution icon."""
        if not os.path.exists(self.ico_path) or not os.path.exists(self.png_path):
            print("[TimerApp] Generating high-quality icon assets...")
            size = 256
            img = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Draw premium dark gradient background
            for r in range(120, 0, -1):
                factor = r / 120.0
                color_r = int(20 * factor + 54 * (1.0 - factor))
                color_g = int(24 * factor + 86 * (1.0 - factor))
                color_b = int(72 * factor + 224 * (1.0 - factor))
                draw.ellipse([128 - r, 128 - r, 128 + r, 128 + r], fill=(color_r, color_g, color_b, 255))
                
            # Draw elegant clock arc ring
            draw.arc([48, 48, 208, 208], start=0, end=360, fill=(255, 255, 255, 210), width=10)
            
            # Draw minimal clock hands (10:10 format)
            draw.line([128, 128, 85, 85], fill=(255, 255, 255, 240), width=8)  # Hour hand
            draw.line([128, 128, 175, 85], fill=(255, 80, 100, 255), width=6)  # Accent minute hand
            
            draw.ellipse([120, 120, 136, 136], fill=(255, 255, 255, 255))
            
            img.save(self.png_path, format="PNG")
            img.save(self.ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            
        self.icon_img = Image.open(self.png_path)

    def load_config(self):
        """Loads and normalizes task profiles from config.json."""
        config_path = os.path.join(self.app_dir, "config.json")
        if not os.path.exists(config_path):
            self.current_lang = "zh"
            return []
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                tasks = data.get("tasks", [])
                self.current_lang = data.get("language", "zh")
                if self.current_lang not in ("zh", "en"):
                    self.current_lang = "zh"
                
                # Normalize types to prevent JSON schema compatibility issues
                for task in tasks:
                    task["is_paused"] = bool(task.get("is_paused", False))
                    task["sound_path"] = str(task.get("sound_path", "C:/Windows/Media/Windows Default.wav"))
                    if task["type"] == "timer":
                        task["duration_minutes"] = float(task.get("duration_minutes", 20.0))
                        task["is_auto_loop"] = bool(task.get("is_auto_loop", True))
                        task["target_time"] = float(task.get("target_time", 0.0))
                        task["remaining_seconds"] = float(task.get("remaining_seconds", 0.0))
                    elif task["type"] == "alarm":
                        task["alarm_time"] = str(task.get("alarm_time", "08:30"))
                        task["repeat_days"] = [int(x) for x in task.get("repeat_days", [])]
                        task["target_time"] = float(task.get("target_time", 0.0))
                return tasks
        except Exception as e:
            print(f"[TimerApp] Error loading config: {e}")
            self.current_lang = "zh"
            return []

    def save_config(self):
        """Saves current memory task configurations into local config.json."""
        config_path = os.path.join(self.app_dir, "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"tasks": self.tasks, "language": self.current_lang}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TimerApp] Error saving config: {e}")

    def trigger_merged_notification(self, missed_tasks):
        """Pushes a single native Toast displaying all missed alerts in one visual card."""
        if not missed_tasks:
            return
            
        try:
            lang = self.current_lang
            if len(missed_tasks) == 1:
                title = self.loc[lang]["toast_title_single"]
                message = missed_tasks[0]["name"]
            else:
                title = self.loc[lang]["toast_title_multi"].format(count=len(missed_tasks))
                message = "\n".join([f"• {t['name']}" for t in missed_tasks])
                
            xml_str = f"""
            <toast duration="short">
                <visual>
                    <binding template="ToastGeneric">
                        <text>{title}</text>
                        <text>{message}</text>
                        <image placement="appLogoOverride" hint-crop="circle" src="file:///{self.png_path.replace(chr(92), '/')}"/>
                    </binding>
                </visual>
                <audio silent="true"/>
            </toast>
            """
            xml_doc = win_xml.XmlDocument()
            xml_doc.load_xml(xml_str)
            
            notifier = win_notify.ToastNotificationManager.create_toast_notifier_with_id(self.app_id)
            toast = win_notify.ToastNotification(xml_doc)
            notifier.show(toast)
            print(f"[TimerApp] Toast delivered: '{title}' - '{message}'")
            
            # Asynchronously play the sound associated with the first missed task
            first_task = missed_tasks[0]
            sound_filepath = first_task.get("sound_path", "C:/Windows/Media/Windows Default.wav")
            try:
                if os.path.exists(sound_filepath):
                    winsound.PlaySound(sound_filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception as se:
                print(f"[TimerApp] Audio stream warning: {se}")
        except Exception as e:
            print(f"[TimerApp] Error sending notification: {e}")

    def check_and_compensate_missed_tasks(self, curr_time):
        """Checks for expired tasks during sleep or shutdown and delivers a combined Toast."""
        missed_tasks = []
        with self.lock:
            for task in self.tasks:
                if task["is_paused"]:
                    continue
                if curr_time >= task["target_time"]:
                    missed_tasks.append(task)
                    
                    # Recalculate and reschedule targets
                    if task["type"] == "timer":
                        if task["is_auto_loop"]:
                            task["target_time"] = curr_time + (task["duration_minutes"] * 60.0)
                        else:
                            task["is_paused"] = True
                    elif task["type"] == "alarm":
                        task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"])
                        
        if missed_tasks:
            self.trigger_merged_notification(missed_tasks)
            self.save_config()
            # Thread-safe GUI list redraw if visible
            if self.root and self.root.winfo_exists() and self.root.winfo_viewable():
                self.root.after(0, self.render_task_list)

    def timer_loop(self):
        """Ultra-low power multi-task background scheduler."""
        while True:
            if not self.is_running:
                break
                
            curr = time.time()
            triggered_tasks = []
            
            with self.lock:
                for task in self.tasks:
                    if task["is_paused"]:
                        continue
                    if curr >= task["target_time"]:
                        triggered_tasks.append(task)
                        
                        # Reschedule next trigger
                        if task["type"] == "timer":
                            if task["is_auto_loop"]:
                                interval = task["duration_minutes"] * 60.0
                                # Align relative to previous target to avoid drift
                                if curr - task["target_time"] > interval:
                                    task["target_time"] = curr + interval
                                else:
                                    task["target_time"] = task["target_time"] + interval
                            else:
                                task["is_paused"] = True
                        elif task["type"] == "alarm":
                            task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"])
                            
            if triggered_tasks:
                self.trigger_merged_notification(triggered_tasks)
                self.save_config()
                if self.root and self.root.winfo_exists() and self.root.winfo_viewable():
                    self.root.after(0, self.render_task_list)
                    
            time.sleep(0.5)

    def on_system_wake(self):
        """System wakeup event interceptor."""
        print("[TimerApp] System woke up from sleep/modern standby. Compensating missed alarms...")
        self.check_and_compensate_missed_tasks(time.time())

    def toggle_task(self, task_id):
        """Pauses or resumes an individual task card."""
        with self.lock:
            for task in self.tasks:
                if task["id"] == task_id:
                    if task["is_paused"]:
                        task["is_paused"] = False
                        if task["type"] == "timer":
                            task["target_time"] = time.time() + task["remaining_seconds"]
                        elif task["type"] == "alarm":
                            task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"])
                    else:
                        task["is_paused"] = True
                        if task["type"] == "timer":
                            task["remaining_seconds"] = max(0.0, task["target_time"] - time.time())
                    break
        self.save_config()
        self.render_task_list()

    def delete_task(self, task_id):
        """Deletes an individual task card from memory and persistence."""
        with self.lock:
            self.tasks = [t for t in self.tasks if t["id"] != task_id]
        self.save_config()
        self.render_task_list()

    def reset_task(self, task_id):
        """Resets an individual task card back to its starting state."""
        with self.lock:
            for task in self.tasks:
                if task["id"] == task_id:
                    if task["type"] == "timer":
                        task["remaining_seconds"] = task["duration_minutes"] * 60.0
                        if not task["is_paused"]:
                            task["target_time"] = time.time() + task["remaining_seconds"]
                    elif task["type"] == "alarm":
                        task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"])
                    break
        self.save_config()
        self.render_task_list()

    def edit_task(self, task_id):
        """Opens a grab-focused, centered modal dialog to edit settings of an active task/alarm."""
        with self.lock:
            target_task = None
            for t in self.tasks:
                if t["id"] == task_id:
                    target_task = t
                    break
                    
        if not target_task:
            return
            
        lang = self.current_lang
        
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(self.loc[lang]["edit_task_title"])
        dialog.geometry("450x560")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.configure(fg_color="#111827")
        dialog.grab_set()
        
        # Center relative to root
        self.root.update_idletasks()
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        dw, dh = 450, 560
        x = rx + (rw - dw) // 2
        y = ry + (rh - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")
        
        if pywinstyles:
            try:
                pywinstyles.apply_style(dialog, "acrylic")
                pywinstyles.change_header_color(dialog, "#111827")
                pywinstyles.change_title_color(dialog, "#60A5FA")
            except Exception:
                pass
                
        # Title Label
        title_font = ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        info_font = ctk.CTkFont(family="Segoe UI", size=12)
        
        header_lbl = ctk.CTkLabel(
            dialog,
            text=self.loc[lang]["edit_task_header"],
            font=title_font,
            text_color="#60A5FA"
        )
        header_lbl.pack(anchor="w", padx=25, pady=(15, 10))
        
        # Main form frame
        form_frame = ctk.CTkFrame(
            dialog,
            corner_radius=12,
            fg_color="#1E293B",
            border_width=1,
            border_color="#334155"
        )
        form_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        # 1. Remarks (Name) Textbox
        name_lbl = ctk.CTkLabel(form_frame, text=self.loc[lang]["msg_label"], font=label_font, text_color="#E5E7EB")
        name_lbl.pack(anchor="w", padx=20, pady=(12, 2))
        
        name_textbox = ctk.CTkTextbox(
            form_frame,
            font=info_font,
            height=60,
            border_color="#4B5563",
            border_width=1
        )
        name_textbox.pack(fill="x", padx=20, pady=(0, 10))
        name_textbox.insert("1.0", target_task["name"])
        
        # 2. Conditional Fields
        dialog_repeat_vars = []
        loop_var = None
        duration_entry = None
        h_entry = None
        m_entry = None
        
        if target_task["type"] == "timer":
            timer_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
            timer_frame.pack(fill="x", padx=20, pady=5)
            
            duration_lbl = ctk.CTkLabel(timer_frame, text=self.loc[lang]["timer_duration"], font=label_font, text_color="#E5E7EB")
            duration_lbl.pack(anchor="w", pady=(0, 2))
            
            duration_entry = ctk.CTkEntry(
                timer_frame,
                font=info_font,
                height=32,
                border_color="#4B5563"
            )
            duration_entry.pack(fill="x", pady=(0, 8))
            duration_entry.insert(0, str(target_task["duration_minutes"]))
            
            loop_var = ctk.BooleanVar(value=target_task.get("is_auto_loop", True))
            loop_cb = ctk.CTkCheckBox(
                timer_frame,
                text=self.loc[lang]["timer_loop"],
                variable=loop_var,
                font=info_font,
                checkbox_width=18,
                checkbox_height=18
            )
            loop_cb.pack(anchor="w", pady=(0, 5))
            
        else: # alarm
            alarm_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
            alarm_frame.pack(fill="x", padx=20, pady=5)
            
            time_lbl = ctk.CTkLabel(alarm_frame, text=self.loc[lang]["alarm_time"], font=label_font, text_color="#E5E7EB")
            time_lbl.pack(anchor="w", pady=(0, 2))
            
            time_entry_row = ctk.CTkFrame(alarm_frame, fg_color="transparent")
            time_entry_row.pack(fill="x", pady=(0, 8))
            
            h_val, m_val = target_task["alarm_time"].split(":")
            
            h_entry = ctk.CTkEntry(
                time_entry_row,
                width=60,
                placeholder_text=self.loc[lang]["alarm_hour_placeholder"],
                font=info_font,
                height=32,
                border_color="#4B5563",
                justify="center"
            )
            h_entry.pack(side="left")
            h_entry.insert(0, h_val)
            
            colon_lbl = ctk.CTkLabel(
                time_entry_row,
                text=":",
                font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
                text_color="#9CA3AF"
            )
            colon_lbl.pack(side="left", padx=8)
            
            m_entry = ctk.CTkEntry(
                time_entry_row,
                width=60,
                placeholder_text=self.loc[lang]["alarm_minute_placeholder"],
                font=info_font,
                height=32,
                border_color="#4B5563",
                justify="center"
            )
            m_entry.pack(side="left")
            m_entry.insert(0, m_val)
            
            def on_dialog_hour_keyrelease(event):
                val = h_entry.get()
                if " " in val:
                    h_entry.delete(0, 'end')
                    h_entry.insert(0, val.replace(" ", ""))
                    m_entry.focus_set()
                    return
                if len(val.strip()) >= 2 and val.strip().isdigit():
                    m_entry.focus_set()
                    m_entry.select_range(0, 'end')
                    m_entry.icursor('end')
            
            def on_dialog_hour_keypress(event):
                if event.keysym == "Right":
                    idx = h_entry.index("insert")
                    if idx == len(h_entry.get()):
                        m_entry.focus_set()
                        m_entry.icursor(0)
                        
            def on_dialog_minute_keypress(event):
                val = m_entry.get()
                if event.keysym == "Backspace" and not val:
                    h_entry.focus_set()
                    h_entry.icursor('end')
                elif event.keysym == "Left":
                    idx = m_entry.index("insert")
                    if idx == 0:
                        h_entry.focus_set()
                        h_entry.icursor('end')
                        
            h_entry.bind("<KeyRelease>", on_dialog_hour_keyrelease)
            h_entry.bind("<KeyPress>", on_dialog_hour_keypress)
            m_entry.bind("<KeyPress>", on_dialog_minute_keypress)
            
            rep_lbl = ctk.CTkLabel(alarm_frame, text=self.loc[lang]["repeat_cycle"], font=label_font, text_color="#E5E7EB")
            rep_lbl.pack(anchor="w", pady=(0, 2))
            
            everyday_v = ctk.BooleanVar(value=False)
            
            def on_dialog_everyday_changed():
                is_checked = everyday_v.get()
                for _, var in dialog_repeat_vars:
                    var.set(is_checked)
                    
            def on_dialog_day_changed():
                all_checked = all(var.get() for _, var in dialog_repeat_vars)
                everyday_v.set(all_checked)
                
            everyday_cb = ctk.CTkCheckBox(
                alarm_frame,
                text=self.loc[lang]["everyday"],
                variable=everyday_v,
                font=info_font,
                checkbox_width=18,
                checkbox_height=18,
                command=on_dialog_everyday_changed
            )
            everyday_cb.pack(anchor="w", pady=(0, 5))
            
            days_row = ctk.CTkFrame(alarm_frame, fg_color="transparent")
            days_row.pack(fill="x", pady=(0, 5))
            
            weekdays_labels = self.loc[lang]["weekdays"]
            current_repeat_days = target_task.get("repeat_days", [])
            
            for i, day in enumerate(weekdays_labels):
                day_num = i + 1
                var = ctk.BooleanVar(value=(day_num in current_repeat_days))
                cb = ctk.CTkCheckBox(
                    days_row,
                    text=day,
                    variable=var,
                    width=42 if lang == "en" else 40,
                    checkbox_width=16,
                    checkbox_height=16,
                    font=info_font,
                    border_width=2,
                    command=on_dialog_day_changed
                )
                cb.pack(side="left", padx=1)
                dialog_repeat_vars.append((day_num, var))
                
            if current_repeat_days and len(current_repeat_days) == 7:
                everyday_v.set(True)
                
        # 3. Sound Selector
        sound_lbl = ctk.CTkLabel(form_frame, text=self.loc[lang]["sound_label"], font=label_font, text_color="#E5E7EB")
        sound_lbl.pack(anchor="w", padx=20, pady=(8, 2))
        
        sound_combo = ctk.CTkComboBox(
            form_frame,
            values=list(self.sound_options[lang].keys()),
            font=info_font,
            height=32,
            state="readonly"
        )
        sound_combo.pack(fill="x", padx=20, pady=(0, 8))
        
        current_sound_path = target_task.get("sound_path", "")
        selected_sound_key = None
        for k, v in self.sound_options[lang].items():
            if v == current_sound_path:
                selected_sound_key = k
                break
        if selected_sound_key is None:
            selected_sound_key = "🔔 系统默认 (System Default)" if lang == "zh" else "🔔 System Default"
        sound_combo.set(selected_sound_key)
        
        def on_dialog_sound_selected(val):
            s_path = self.sound_options[lang].get(val, "C:/Windows/Media/Windows Default.wav")
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
                if os.path.exists(s_path):
                    winsound.PlaySound(s_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
                
        sound_combo.configure(command=on_dialog_sound_selected)
        
        # 4. Error / Validation Label
        dialog_error_lbl = ctk.CTkLabel(form_frame, text="", font=info_font, text_color="#EF4444")
        dialog_error_lbl.pack(pady=(5, 5))
        
        # 5. Buttons row
        btn_row = ctk.CTkFrame(form_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(5, 12))
        
        cancel_btn = ctk.CTkButton(
            btn_row,
            text=self.loc[lang]["dialog_cancel"],
            font=label_font,
            height=32,
            fg_color="#374151",
            hover_color="#4B5563",
            command=dialog.destroy
        )
        cancel_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        def save_edits():
            name_val = name_textbox.get("1.0", "end-1c").strip()
            if not name_val:
                dialog_error_lbl.configure(text=self.loc[lang]["error_msg_empty"], text_color="#EF4444")
                return
                
            selected_s = sound_combo.get()
            s_path = self.sound_options[lang].get(selected_s, "C:/Windows/Media/Windows Default.wav")
            
            if target_task["type"] == "timer":
                dur_val = duration_entry.get().strip()
                minutes = self.validate_timer_duration(dur_val)
                if minutes is None:
                    dialog_error_lbl.configure(text=self.loc[lang]["error_timer_invalid"], text_color="#EF4444")
                    return
                    
                with self.lock:
                    target_task["name"] = name_val
                    target_task["sound_path"] = s_path
                    target_task["is_auto_loop"] = loop_var.get()
                    
                    if abs(target_task["duration_minutes"] - minutes) > 1e-5:
                        target_task["duration_minutes"] = minutes
                        target_task["remaining_seconds"] = minutes * 60.0
                        if not target_task["is_paused"]:
                            target_task["target_time"] = time.time() + target_task["remaining_seconds"]
                            
            else: # alarm
                h_val = h_entry.get().strip()
                m_val = m_entry.get().strip()
                alarm_time = self.validate_alarm_time(h_val, m_val)
                if alarm_time is None:
                    dialog_error_lbl.configure(text=self.loc[lang]["error_alarm_invalid"], text_color="#EF4444")
                    return
                    
                rep_days = []
                for day_num, var in dialog_repeat_vars:
                    if var.get():
                        rep_days.append(day_num)
                        
                with self.lock:
                    target_task["name"] = name_val
                    target_task["sound_path"] = s_path
                    
                    if target_task["alarm_time"] != alarm_time or target_task["repeat_days"] != rep_days:
                        target_task["alarm_time"] = alarm_time
                        target_task["repeat_days"] = rep_days
                        if not target_task["is_paused"]:
                            target_task["target_time"] = calculate_next_alarm(alarm_time, rep_days)
                            
            self.save_config()
            self.render_task_list()
            dialog.destroy()
            
        save_btn = ctk.CTkButton(
            btn_row,
            text=self.loc[lang]["dialog_save"],
            font=label_font,
            height=32,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=save_edits
        )
        save_btn.pack(side="right", fill="x", expand=True)

    def global_pause(self):
        """Pauses all currently running tasks."""
        with self.lock:
            for task in self.tasks:
                if not task["is_paused"]:
                    task["is_paused"] = True
                    if task["type"] == "timer":
                        task["remaining_seconds"] = max(0.0, task["target_time"] - time.time())
        self.save_config()
        self.render_task_list()

    def global_resume(self):
        """Resumes all paused tasks."""
        with self.lock:
            for task in self.tasks:
                if task["is_paused"]:
                    task["is_paused"] = False
                    if task["type"] == "timer":
                        task["target_time"] = time.time() + task["remaining_seconds"]
                    elif task["type"] == "alarm":
                        task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"])
        self.save_config()
        self.render_task_list()

    def global_pause_tray(self, icon=None, item=None):
        self.global_pause()
        if self.root and self.root.winfo_exists() and self.root.winfo_viewable():
            self.root.after(0, self.render_task_list)

    def global_resume_tray(self, icon=None, item=None):
        self.global_resume()
        if self.root and self.root.winfo_exists() and self.root.winfo_viewable():
            self.root.after(0, self.render_task_list)

    def build_gui(self):
        """Constructs the high-fidelity dark-themed CustomTkinter UI."""
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title(self.loc[self.current_lang]["title"])
        self.root.geometry("880x600")
        self.root.resizable(True, True)
        self.root.minsize(820, 550)
        
        # Apply Apple-like Frosted Glass "Liquid Glass" theme using pywinstyles (with flat fallback)
        if pywinstyles:
            try:
                pywinstyles.apply_style(self.root, "acrylic")
                pywinstyles.change_header_color(self.root, "#111827")
                pywinstyles.change_title_color(self.root, "#60A5FA")
            except Exception as e:
                print(f"[TimerApp] Custom titlebar styling note: {e}")
        
        try:
            self.root.iconbitmap(self.ico_path)
        except Exception:
            pass
            
        title_font = ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        info_font = ctk.CTkFont(family="Segoe UI", size=12)
        
        # Main flat deep slate container (translucent looking #111827)
        self.main_container = ctk.CTkFrame(
            self.root,
            fg_color="#111827",
            corner_radius=0
        )
        self.main_container.pack(fill="both", expand=True, padx=0, pady=0)
        
        # 1. Top Header Frame
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.pack(fill="x", padx=30, pady=(20, 10))
        
        self.title_label = ctk.CTkLabel(
            header_frame, 
            text=self.loc[self.current_lang]["title"], 
            font=title_font,
            text_color="#60A5FA"
        )
        self.title_label.pack(anchor="w", pady=(0, 2))
        
        self.subtitle_label = ctk.CTkLabel(
            header_frame,
            text=self.loc[self.current_lang]["subtitle"],
            font=info_font,
            text_color="#9CA3AF"
        )
        self.subtitle_label.pack(anchor="w")
        
        # 2. Split Workspace Layout Frame (Dual-Column)
        self.split_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.split_frame.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Left Panel: Active Ticking Task List Dashboard (60% width)
        self.left_panel = ctk.CTkFrame(self.split_frame, fg_color="transparent")
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))
        
        # Controls Frame (Title + Pause/Resume buttons horizontal layout)
        controls_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        controls_frame.pack(fill="x", pady=(0, 10))
        
        lang = self.current_lang
        self.list_title_label = ctk.CTkLabel(
            controls_frame,
            text=self.loc[lang]["list_title"],
            font=label_font,
            text_color="#E5E7EB"
        )
        self.list_title_label.pack(side="left", anchor="w")
        
        # Pause All and Resume All buttons on the right side of the list title
        self.global_resume_btn = ctk.CTkButton(
            controls_frame,
            text=self.loc[lang]["resume_all"],
            font=info_font,
            height=26,
            width=80,
            fg_color="#10B981",
            hover_color="#059669",
            command=self.global_resume
        )
        self.global_resume_btn.pack(side="right", padx=(5, 0))
        
        self.global_pause_btn = ctk.CTkButton(
            controls_frame,
            text=self.loc[lang]["pause_all"],
            font=info_font,
            height=26,
            width=80,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.global_pause
        )
        self.global_pause_btn.pack(side="right", padx=5)
        
        # Scrollable Task list frame (ticking cards directly inside here)
        self.task_list_frame = ctk.CTkScrollableFrame(
            self.left_panel,
            fg_color="transparent"
        )
        self.task_list_frame.pack(fill="both", expand=True, pady=0)
        
        # Bind canvas configuration to auto-adjust grid layout columns and scrollbar dynamically
        self.task_list_frame._parent_canvas.bind(
            "<Configure>", 
            self.on_list_frame_configure, 
            add="+"
        )
        
        # Right Panel: Task Creation Control Center (40% width)
        self.right_panel = ctk.CTkFrame(self.split_frame, width=340, fg_color="transparent")
        self.right_panel.pack(side="right", fill="both", padx=(15, 0))
        self.right_panel.pack_propagate(False) # Keep width constant
        
        form_frame = ctk.CTkFrame(
            self.right_panel, 
            corner_radius=12, 
            fg_color="#1E293B", 
            border_width=1, 
            border_color="#334155"
        )
        form_frame.pack(fill="both", expand=True)
        
        # Tab selection: Segmented Button
        self.segmented_button = ctk.CTkSegmentedButton(
            form_frame,
            values=[self.loc[lang]["tab_timer"], self.loc[lang]["tab_alarm"]],
            command=self.on_segmented_btn_changed,
            font=label_font,
            height=32
        )
        self.segmented_button.pack(padx=20, pady=(15, 5), fill="x")
        self.segmented_button.set(self.loc[lang]["tab_timer"])
        
        # Placeholder container frame to ensure dynamic fields are always right below the tab segmented button
        self.fields_container_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        self.fields_container_frame.pack(fill="x", padx=0, pady=0)
        
        # Sub-form 1: Timer Fields
        self.timer_fields_frame = ctk.CTkFrame(self.fields_container_frame, fg_color="transparent")
        self.timer_fields_frame.pack(fill="x", padx=20, pady=5)
        
        self.timer_duration_label = ctk.CTkLabel(self.timer_fields_frame, text=self.loc[lang]["timer_duration"], font=label_font, text_color="#E5E7EB")
        self.timer_duration_label.pack(anchor="w", pady=(5, 2))
        
        timer_input_row = ctk.CTkFrame(self.timer_fields_frame, fg_color="transparent")
        timer_input_row.pack(fill="x", pady=(0, 5))
        
        self.time_entry = ctk.CTkEntry(
            timer_input_row, 
            placeholder_text=self.loc[lang]["timer_placeholder"], 
            font=info_font,
            height=32,
            border_color="#4B5563"
        )
        self.time_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.time_entry.insert(0, "20.0")
        self.time_entry.bind("<Return>", lambda e: self.on_start_clicked())
        
        self.timer_start_btn = ctk.CTkButton(
            timer_input_row,
            text=self.loc[lang]["add_task_short"],
            command=self.on_start_clicked,
            font=label_font,
            height=32,
            width=80,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8"
        )
        self.timer_start_btn.pack(side="right")
        
        self.timer_loop_var = ctk.BooleanVar(value=True)
        self.timer_loop_cb = ctk.CTkCheckBox(
            self.timer_fields_frame,
            text=self.loc[lang]["timer_loop"],
            variable=self.timer_loop_var,
            font=info_font,
            checkbox_width=18,
            checkbox_height=18
        )
        self.timer_loop_cb.pack(anchor="w", pady=5)
        
        # Sub-form 2: Alarm Fields (hidden initially)
        self.alarm_fields_frame = ctk.CTkFrame(self.fields_container_frame, fg_color="transparent")
        
        self.alarm_time_label = ctk.CTkLabel(self.alarm_fields_frame, text=self.loc[lang]["alarm_time"], font=label_font, text_color="#E5E7EB")
        self.alarm_time_label.pack(anchor="w", pady=(5, 2))
        
        entry_row = ctk.CTkFrame(self.alarm_fields_frame, fg_color="transparent")
        entry_row.pack(fill="x", pady=(0, 5))
        
        self.alarm_hour_entry = ctk.CTkEntry(
            entry_row,
            width=60,
            placeholder_text=self.loc[lang]["alarm_hour_placeholder"],
            font=info_font,
            height=32,
            border_color="#4B5563",
            justify="center"
        )
        self.alarm_hour_entry.pack(side="left")
        
        self.colon_label = ctk.CTkLabel(
            entry_row, 
            text=":", 
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), 
            text_color="#9CA3AF"
        )
        self.colon_label.pack(side="left", padx=8)
        
        self.alarm_minute_entry = ctk.CTkEntry(
            entry_row,
            width=60,
            placeholder_text=self.loc[lang]["alarm_minute_placeholder"],
            font=info_font,
            height=32,
            border_color="#4B5563",
            justify="center"
        )
        self.alarm_minute_entry.pack(side="left")
        
        self.alarm_start_btn = ctk.CTkButton(
            entry_row,
            text=self.loc[lang]["add_task_short"],
            command=self.on_start_clicked,
            font=label_font,
            height=32,
            width=80,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8"
        )
        self.alarm_start_btn.pack(side="right", padx=(8, 0), fill="x", expand=True)
        
        # Key bindings for auto-tabbing and keyboard focus management
        self.alarm_hour_entry.bind("<KeyRelease>", self.on_hour_keyrelease)
        self.alarm_hour_entry.bind("<KeyPress>", self.on_hour_keypress)
        self.alarm_hour_entry.bind("<KeyPress>", self.on_minute_keypress)
        self.alarm_hour_entry.bind("<Return>", lambda e: self.on_start_clicked())
        self.alarm_minute_entry.bind("<Return>", lambda e: self.on_start_clicked())
        
        self.repeat_label = ctk.CTkLabel(self.alarm_fields_frame, text=self.loc[lang]["repeat_cycle"], font=label_font, text_color="#E5E7EB")
        self.repeat_label.pack(anchor="w", pady=(5, 2))
        
        self.everyday_var = ctk.BooleanVar(value=False)
        self.everyday_cb = ctk.CTkCheckBox(
            self.alarm_fields_frame,
            text=self.loc[lang]["everyday"],
            variable=self.everyday_var,
            font=info_font,
            checkbox_width=18,
            checkbox_height=18,
            command=self.on_everyday_changed
        )
        self.everyday_cb.pack(anchor="w", pady=(2, 5))
        
        days_frame = ctk.CTkFrame(self.alarm_fields_frame, fg_color="transparent")
        days_frame.pack(fill="x", pady=(0, 5))
        
        self.repeat_vars = []
        self.repeat_checkboxes = []
        weekdays_label = self.loc[lang]["weekdays"]
        for i, day in enumerate(weekdays_label):
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(
                days_frame,
                text=day,
                variable=var,
                width=42 if lang == "en" else 40,
                checkbox_width=16,
                checkbox_height=16,
                font=info_font,
                border_width=2,
                command=self.on_day_changed
            )
            cb.pack(side="left", padx=1)
            self.repeat_vars.append((i + 1, var))
            self.repeat_checkboxes.append(cb)
            
        # Common Input: Sound Picker
        self.sound_label = ctk.CTkLabel(form_frame, text=self.loc[lang]["sound_label"], font=label_font, text_color="#E5E7EB")
        self.sound_label.pack(anchor="w", padx=20, pady=(5, 2))
        
        self.sound_combobox = ctk.CTkComboBox(
            form_frame,
            values=list(self.sound_options[lang].keys()),
            command=self.on_sound_selected,
            font=info_font,
            height=32,
            state="readonly"
        )
        self.sound_combobox.pack(fill="x", padx=20, pady=(0, 10))
        self.sound_combobox.set("🔔 经典闹铃 (Classic Alarm)" if lang == "zh" else "🔔 Classic Alarm")
 
        # Common Input: Message Text
        self.msg_label = ctk.CTkLabel(form_frame, text=self.loc[lang]["msg_label"], font=label_font, text_color="#E5E7EB")
        self.msg_label.pack(anchor="w", padx=20, pady=(15, 2))
        
        self.msg_entry = ctk.CTkTextbox(
            form_frame, 
            font=info_font,
            height=60,
            border_color="#4B5563",
            border_width=1
        )
        self.msg_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.msg_entry.insert("1.0", self.loc[lang]["msg_default"])
        

        
        # Error / Validation Label
        self.error_label = ctk.CTkLabel(form_frame, text="", font=info_font, text_color="#EF4444")
        self.error_label.pack(pady=(0, 10))
        
        # Floating Language Switch Button in the top-right corner of root
        self.lang_btn = ctk.CTkButton(
            self.root,
            text="EN" if lang == "zh" else "中",
            width=50,
            height=26,
            fg_color="#1F2937",
            hover_color="#374151",
            text_color="#60A5FA",
            border_width=1,
            border_color="#4B5563",
            corner_radius=13,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self.toggle_language
        )
        self.lang_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)
        self.lang_btn.lift()
        
        # Floating PiP Toggle Button in top-right
        self.pip_btn = ctk.CTkButton(
            self.root,
            text="📌",
            width=36,
            height=26,
            fg_color="#1F2937",
            hover_color="#374151",
            text_color="#60A5FA",
            border_width=1,
            border_color="#4B5563",
            corner_radius=13,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self.toggle_pip_mode
        )
        self.pip_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-80, y=20)
        self.pip_btn.lift()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        # Initial Render & Loop Waking
        self.render_task_list()
        self.update_gui_status()

    def toggle_language(self):
        """Toggles active application language and updates all UI elements dynamically."""
        self.current_lang = "en" if self.current_lang == "zh" else "zh"
        self.save_config()
        self.lang_btn.configure(text="EN" if self.current_lang == "zh" else "中")
        self.retranslate_ui()

    def toggle_pip_mode(self):
        """Toggles picture-in-picture float mode."""
        if self.pip_window and self.pip_window.winfo_exists():
            self.pip_window.close_pip()
        else:
            self.hide_window()
            self.pip_window = PiPWindow(self)

    def on_sound_selected(self, val):
        """Plays the selected sound as a quick preview."""
        lang = self.current_lang
        sound_filepath = self.sound_options[lang].get(val, "C:/Windows/Media/Windows Default.wav")
        try:
            # Stop any running preview first
            winsound.PlaySound(None, winsound.SND_PURGE)
            if os.path.exists(sound_filepath):
                winsound.PlaySound(sound_filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception as e:
            print(f"[TimerApp] Sound preview warning: {e}")

    def retranslate_ui(self):
        """Updates all visible texts in the UI to match self.current_lang."""
        lang = self.current_lang
        
        # 1. Root window title
        self.root.title(self.loc[lang]["title"])
        
        # 2. Header
        self.title_label.configure(text=self.loc[lang]["title"])
        self.subtitle_label.configure(text=self.loc[lang]["subtitle"])
        
        # 3. Segmented Button values and tab state
        old_val = self.segmented_button.get()
        if old_val in ("⏳ 定时器", "⏳ Timer"):
            new_val = self.loc[lang]["tab_timer"]
        else:
            new_val = self.loc[lang]["tab_alarm"]
            
        self.segmented_button.configure(values=[self.loc[lang]["tab_timer"], self.loc[lang]["tab_alarm"]])
        self.segmented_button.set(new_val)
        
        # 4. Form Timer / Alarm labels & placeholders
        self.timer_duration_label.configure(text=self.loc[lang]["timer_duration"])
        self.time_entry.configure(placeholder_text=self.loc[lang]["timer_placeholder"])
        self.timer_loop_cb.configure(text=self.loc[lang]["timer_loop"])
        
        self.alarm_time_label.configure(text=self.loc[lang]["alarm_time"])
        self.alarm_hour_entry.configure(placeholder_text=self.loc[lang]["alarm_hour_placeholder"])
        self.alarm_minute_entry.configure(placeholder_text=self.loc[lang]["alarm_minute_placeholder"])
        
        self.repeat_label.configure(text=self.loc[lang]["repeat_cycle"])
        self.everyday_cb.configure(text=self.loc[lang]["everyday"])
        
        # 5. Weekday checkboxes
        weekdays = self.loc[lang]["weekdays"]
        for idx, cb in enumerate(self.repeat_checkboxes):
            cb.configure(text=weekdays[idx], width=42 if lang == "en" else 40)
            
        # 6. Message fields & Sound selector translation mapping
        self.sound_label.configure(text=self.loc[lang]["sound_label"])
        prev_selection = self.sound_combobox.get()
        old_lang = "en" if lang == "zh" else "zh"
        found_file = self.sound_options[old_lang].get(prev_selection, "C:/Windows/Media/Windows Default.wav")
        new_selection = "🔔 系统默认 (System Default)" if lang == "zh" else "🔔 System Default"
        for k, v in self.sound_options[lang].items():
            if v == found_file:
                new_selection = k
                break
        self.sound_combobox.configure(values=list(self.sound_options[lang].keys()))
        self.sound_combobox.set(new_selection)

        self.msg_label.configure(text=self.loc[lang]["msg_label"])
        
        # Swap default content if unchanged
        current_msg = self.msg_entry.get("1.0", "end-1c").strip()
        old_default = self.loc["en" if lang == "zh" else "zh"]["msg_default"]
        if current_msg == old_default:
            self.msg_entry.delete("1.0", "end")
            self.msg_entry.insert("1.0", self.loc[lang]["msg_default"])
        
        # 7. Add Buttons
        self.timer_start_btn.configure(text=self.loc[lang]["add_task_short"])
        self.alarm_start_btn.configure(text=self.loc[lang]["add_task_short"])
        
        # 8. Global Controls & Titles
        self.global_pause_btn.configure(text=self.loc[lang]["pause_all"])
        self.global_resume_btn.configure(text=self.loc[lang]["resume_all"])
        self.list_title_label.configure(text=self.loc[lang]["list_title"])
        
        # 9. Active Tasks and System Tray Menu
        self.render_task_list()
        
        if self.pip_window and self.pip_window.winfo_exists():
            self.pip_window.title(self.loc[lang].get("pip_title", "PiP Mode"))
            # Trigger immediate UI refresh inside PiP window
            self.pip_window.update_pip()
        
        if self.tray_icon:
            menu = pystray.Menu(
                pystray.MenuItem(self.loc[lang]["tray_show"], self.show_window, default=True),
                pystray.MenuItem(self.loc[lang]["tray_pause"], self.global_pause_tray),
                pystray.MenuItem(self.loc[lang]["tray_resume"], self.global_resume_tray),
                pystray.MenuItem(self.loc[lang]["tray_exit"], self.exit_app)
            )
            self.tray_icon.menu = menu
            self.tray_icon.title = self.loc[lang]["tray_title"]

    def on_segmented_btn_changed(self, value):
        """Smoothly toggles sub-form inputs inside the frame."""
        is_timer = (value == self.loc["zh"]["tab_timer"] or value == self.loc["en"]["tab_timer"])
        if is_timer:
            self.alarm_fields_frame.pack_forget()
            self.timer_fields_frame.pack(fill="x", padx=20, pady=5)
        else: # ⏰ 闹钟
            self.timer_fields_frame.pack_forget()
            self.alarm_fields_frame.pack(fill="x", padx=20, pady=5)

    def validate_timer_duration(self, duration_str):
        try:
            val = float(duration_str.strip())
            if val <= 0:
                return None
            return val
        except ValueError:
            return None

    def on_everyday_changed(self):
        is_checked = self.everyday_var.get()
        for _, var in self.repeat_vars:
            var.set(is_checked)

    def on_day_changed(self):
        all_checked = all(var.get() for _, var in self.repeat_vars)
        self.everyday_var.set(all_checked)

    def validate_alarm_time(self, h_str, m_str=""):
        h_str = h_str.strip()
        m_str = m_str.strip()
        
        # Fallback for copy-pasting or combined input in the hour field:
        if not m_str and (":" in h_str or " " in h_str or len(h_str) >= 3):
            time_str = h_str
        elif not m_str and len(h_str) in (1, 2) and h_str.isdigit():
            time_str = h_str
        else:
            if not h_str:
                return None
            if not m_str:
                m_str = "00"
            time_str = f"{h_str} {m_str}"
            
        time_str = time_str.replace(":", " ")
        time_str = re.sub(r"\s+", " ", time_str)
        
        if time_str.isdigit():
            if len(time_str) in (1, 2):
                h = int(time_str)
                m = 0
            elif len(time_str) == 3:
                h = int(time_str[0])
                m = int(time_str[1:])
            elif len(time_str) == 4:
                h = int(time_str[:2])
                m = int(time_str[2:])
            else:
                return None
        else:
            parts = time_str.split(" ")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                h = int(parts[0])
                m = int(parts[1])
            else:
                return None
                
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
        return None

    def on_hour_keyrelease(self, event):
        val = self.alarm_hour_entry.get()
        if " " in val:
            self.alarm_hour_entry.delete(0, 'end')
            self.alarm_hour_entry.insert(0, val.replace(" ", ""))
            self.alarm_minute_entry.focus_set()
            return
            
        if len(val.strip()) >= 2 and val.strip().isdigit():
            self.alarm_minute_entry.focus_set()
            self.alarm_minute_entry.select_range(0, 'end')
            self.alarm_minute_entry.icursor('end')

    def on_hour_keypress(self, event):
        if event.keysym == "Right":
            idx = self.alarm_hour_entry.index("insert")
            if idx == len(self.alarm_hour_entry.get()):
                self.alarm_minute_entry.focus_set()
                self.alarm_minute_entry.icursor(0)

    def on_minute_keypress(self, event):
        val = self.alarm_minute_entry.get()
        if event.keysym == "Backspace" and not val:
            self.alarm_hour_entry.focus_set()
            self.alarm_hour_entry.icursor('end')
        elif event.keysym == "Left":
            idx = self.alarm_minute_entry.index("insert")
            if idx == 0:
                self.alarm_hour_entry.focus_set()
                self.alarm_hour_entry.icursor('end')

    def adjust_scrollbar_visibility(self):
        try:
            canvas = self.task_list_frame._parent_canvas
            scrollbar = self.task_list_frame._scrollbar
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                content_height = bbox[3] - bbox[1]
                canvas_height = canvas.winfo_height()
                if content_height <= canvas_height:
                    scrollbar.grid_forget()
                else:
                    scrollbar.grid(row=0, column=1, sticky="ns", padx=(self.task_list_frame._scrollbar_padx, 0))
        except Exception as e:
            print(f"[Scrollbar] Error adjusting scrollbar: {e}")

    def on_list_frame_configure(self, event):
        new_width = event.width
        if getattr(self, "_last_list_width", 0) != new_width:
            self._last_list_width = new_width
            self.root.after(50, self.relayout_task_cards)

    def relayout_task_cards(self):
        if not self.root or not self.root.winfo_exists():
            return
            
        width = self.task_list_frame._parent_canvas.winfo_width()
        if width <= 200:
            cols = 1
        elif width >= 1050:
            cols = 3
        elif width >= 680:
            cols = 2
        else:
            cols = 1
            
        with self.lock:
            tasks_copy = list(self.tasks)
            
        for c in range(10):
            self.task_list_frame.grid_columnconfigure(c, weight=0, minsize=0)
            
        for c in range(cols):
            self.task_list_frame.grid_columnconfigure(c, weight=1, minsize=320)
            
        for idx, task in enumerate(tasks_copy):
            task_id = task["id"]
            card = self.task_card_widgets.get(task_id)
            if card and card.winfo_exists():
                r = idx // cols
                c = idx % cols
                card.pack_forget()
                card.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
                
        self.adjust_scrollbar_visibility()

    def on_start_clicked(self):
        """Validates inputs, appends a new task profile, and saves config."""
        current_tab = self.segmented_button.get()
        name_str = self.msg_entry.get("1.0", "end-1c").strip()
        lang = self.current_lang
        if not name_str:
            self.error_label.configure(text=self.loc[lang]["error_msg_empty"], text_color="#EF4444")
            return
            
        # Support segmented tab checks in both languages
        is_timer_tab = (current_tab == self.loc["zh"]["tab_timer"] or current_tab == self.loc["en"]["tab_timer"])
        
        if is_timer_tab:
            time_str = self.time_entry.get().strip()
            minutes = self.validate_timer_duration(time_str)
            if minutes is None:
                self.error_label.configure(text=self.loc[lang]["error_timer_invalid"], text_color="#EF4444")
                return
                
            is_loop = self.timer_loop_var.get()
            selected_sound_name = self.sound_combobox.get()
            sound_path = self.sound_options[lang].get(selected_sound_name, "C:/Windows/Media/Windows Default.wav")
            new_task = {
                "id": str(uuid.uuid4()),
                "type": "timer",
                "name": name_str,
                "duration_minutes": minutes,
                "is_auto_loop": is_loop,
                "is_paused": False,
                "created_at": time.time(),
                "target_time": time.time() + (minutes * 60.0),
                "remaining_seconds": minutes * 60.0,
                "sound_path": sound_path
            }
        else: # ⏰ 闹钟
            h_raw = self.alarm_hour_entry.get().strip()
            m_raw = self.alarm_minute_entry.get().strip()
            alarm_time = self.validate_alarm_time(h_raw, m_raw)
            if alarm_time is None:
                self.error_label.configure(text=self.loc[lang]["error_alarm_invalid"], text_color="#EF4444")
                return
                
            repeat_days = []
            for day_num, var in self.repeat_vars:
                if var.get():
                    repeat_days.append(day_num)
                    
            target_epoch = calculate_next_alarm(alarm_time, repeat_days)
            selected_sound_name = self.sound_combobox.get()
            sound_path = self.sound_options[lang].get(selected_sound_name, "C:/Windows/Media/Windows Default.wav")
            new_task = {
                "id": str(uuid.uuid4()),
                "type": "alarm",
                "name": name_str,
                "alarm_time": alarm_time,
                "repeat_days": repeat_days,
                "is_paused": False,
                "is_completed_today": False,
                "target_time": target_epoch,
                "sound_path": sound_path
            }
            
        with self.lock:
            self.tasks.append(new_task)
            
        self.save_config()
        
        # Display green success text
        self.error_label.configure(text=self.loc[lang]["success_add"], text_color="#10B981")
        # Automatically fade out success message after 3 seconds
        self.root.after(3000, lambda: self.error_label.configure(text=""))
        
        # Reset form fields to default values
        self.time_entry.delete(0, 'end')
        self.time_entry.insert(0, "20.0")
        self.alarm_hour_entry.delete(0, 'end')
        self.alarm_minute_entry.delete(0, 'end')
        self.timer_loop_var.set(True)
        self.everyday_var.set(False)
        for _, var in self.repeat_vars:
            var.set(False)
        self.sound_combobox.set("🔔 经典闹铃 (Classic Alarm)" if lang == "zh" else "🔔 Classic Alarm")
        self.msg_entry.delete("1.0", "end")
        self.msg_entry.insert("1.0", self.loc[lang]["msg_default"])
        
        # Redraw GUI Cards
        self.render_task_list()

    def render_task_list(self):
        """Redraws the scrollable frame with highly responsive rounded card sub-frames."""
        if not self.root or not self.root.winfo_exists():
            return
            
        # Clean children
        for widget in self.task_list_frame.winfo_children():
            widget.destroy()
            
        self.task_labels = {}
        self.task_status_badges = {}
        self.task_hourglasses = {}
        self.task_progress_bars = {}
        self.task_card_widgets = {}
        
        with self.lock:
            tasks_copy = list(self.tasks)
            
        lang = self.current_lang
        if not tasks_copy:
            empty_label = ctk.CTkLabel(
                self.task_list_frame,
                text=self.loc[lang]["empty_list"],
                font=ctk.CTkFont(family="Segoe UI", size=13),
                text_color="#9CA3AF"
            )
            empty_label.pack(pady=40)
            return
            
        for task in tasks_copy:
            task_id = task["id"]
            
            # Card frame container (height is dynamic to fit the grid items elegantly)
            card = ctk.CTkFrame(
                self.task_list_frame, 
                fg_color="#1E293B", 
                corner_radius=10, 
                border_width=1, 
                border_color="#334155"
            )
            self.task_card_widgets[task_id] = card
            
            card.grid_columnconfigure(0, weight=0) # Badge LED
            card.grid_columnconfigure(1, weight=1) # Task Name
            card.grid_columnconfigure(2, weight=0) # Control Buttons Frame
            
            # Status Indicator LED
            status_color = "#10B981" if not task["is_paused"] else "#F59E0B"
            status_dot = ctk.CTkLabel(card, text="●", text_color=status_color, font=("Segoe UI", 16))
            status_dot.grid(row=0, column=0, padx=(12, 4), pady=(12, 4), sticky="w")
            self.task_status_badges[task_id] = status_dot
            
            # Name Label (directly in grid column 1)
            name_text = task["name"]
            if len(name_text) > 20:
                name_text = name_text[:18] + "..."
                
            name_label = ctk.CTkLabel(
                card,
                text=name_text,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color="#E5E7EB",
                anchor="w"
            )
            name_label.grid(row=0, column=1, padx=(2, 8), pady=(12, 4), sticky="w")
            
            # Control Buttons Frame on the right side of the header
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=0, column=2, padx=(4, 12), pady=(12, 4), sticky="e")
            
            # Play/Pause Icon trigger
            btn_text = "⏸" if not task["is_paused"] else "▶"
            btn_fg = "#374151" if not task["is_paused"] else "#10B981"
            pause_btn = ctk.CTkButton(
                btn_frame,
                text=btn_text,
                width=28,
                height=28,
                fg_color=btn_fg,
                hover_color="#4B5563",
                corner_radius=6,
                command=lambda tid=task_id: self.toggle_task(tid)
            )
            pause_btn.pack(side="left", padx=2)
            
            # Reset Icon trigger
            reset_btn = ctk.CTkButton(
                btn_frame,
                text="🔄",
                width=28,
                height=28,
                fg_color="#374151",
                hover_color="#4B5563",
                corner_radius=6,
                command=lambda tid=task_id: self.reset_task(tid)
            )
            reset_btn.pack(side="left", padx=2)
            
            # Edit Icon trigger
            edit_btn = ctk.CTkButton(
                btn_frame,
                text="✏️",
                width=28,
                height=28,
                fg_color="#374151",
                hover_color="#3B82F6",
                corner_radius=6,
                command=lambda tid=task_id: self.edit_task(tid)
            )
            edit_btn.pack(side="left", padx=2)
            
            # Trash Icon trigger
            delete_btn = ctk.CTkButton(
                btn_frame,
                text="🗑",
                width=28,
                height=28,
                fg_color="#374151",
                hover_color="#EF4444",
                corner_radius=6,
                command=lambda tid=task_id: self.delete_task(tid)
            )
            delete_btn.pack(side="left", padx=2)
            
            # Massive visual sand hourglass / alarm clock in its own row centered
            canvas_frame = ctk.CTkFrame(card, fg_color="transparent")
            canvas_frame.grid(row=1, column=0, columnspan=3, padx=12, pady=(5, 5))
            
            if task["type"] == "timer":
                ctimer = CTkCircularTimer(canvas_frame, size=280, bg_color="#1E293B")
                ctimer.pack()
                self.task_hourglasses[task_id] = ctimer
            else:
                clock = CTkAlarmClock(canvas_frame, size=280, bg_color="#1E293B")
                clock.pack()
                self.task_hourglasses[task_id] = clock
            
            # Clock Countdown / Status Label in Row 2 (spanning the entire width)
            time_label = ctk.CTkLabel(
                card,
                text=self.loc[lang]["status_waiting"],
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color="#9CA3AF",
                anchor="center",
                justify="center"
            )
            time_label.grid(row=2, column=0, columnspan=3, padx=12, pady=(4, 10), sticky="ew")
            self.task_labels[task_id] = time_label
            
            # Dynamic Card Progress Bar spanning all 3 columns in row 3 (bottom)
            progress_bar = ctk.CTkProgressBar(
                card,
                height=3,
                corner_radius=0,
                fg_color="#374151",
                progress_color="#10B981"
            )
            progress_bar.grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
            progress_bar.set(1.0)
            self.task_progress_bars[task_id] = progress_bar
            
        # Position cards using the dynamic multi-column grid layout
        self.relayout_task_cards()

        # Request immediate visual redraw of ticking components
        self.tick_gui_status()
        
        # Dynamically recalculate content height and hide/show right scrollbar
        self.root.after(50, self.adjust_scrollbar_visibility)

    def tick_gui_status(self):
        """Renders real-time ticking values on card labels."""
        if not self.root or not self.root.winfo_exists() or not self.root.winfo_viewable():
            return
            
        with self.lock:
            tasks_copy = list(self.tasks)
            
        curr = time.time()
        lang = self.current_lang
        for task in tasks_copy:
            task_id = task["id"]
            if task_id not in self.task_labels:
                continue
                
            label = self.task_labels[task_id]
            pbar = self.task_progress_bars.get(task_id)
            hglass_or_clock = self.task_hourglasses.get(task_id)
            
            if task["is_paused"]:
                if task["type"] == "timer":
                    rem = task["remaining_seconds"]
                    rem_min = int(rem // 60)
                    rem_sec = int(rem % 60)
                    label.configure(text=self.loc[lang]["status_paused_rem"].format(min=rem_min, sec=rem_sec), text_color="#F59E0B")
                    total = task["duration_minutes"] * 60.0
                    ratio = max(0.0, min(1.0, rem / total)) if total > 0.0 else 0.0
                    if pbar:
                        pbar.set(ratio)
                        pbar.configure(progress_color="#F59E0B")
                    if hglass_or_clock:
                        time_str = f"{rem_min:02d}:{rem_sec:02d}"
                        hglass_or_clock.set_progress(ratio, is_paused=True, color="#F59E0B", time_str=time_str)
                else:
                    label.configure(text=self.loc[lang]["status_paused"], text_color="#F59E0B")
                    if pbar:
                        pbar.set(1.0)
                        pbar.configure(progress_color="#F59E0B")
                    if hglass_or_clock:
                        hglass_or_clock.set_progress(1.0, is_paused=True, color="#F59E0B")
            else:
                if task["type"] == "timer":
                    remaining = task["target_time"] - curr
                    if remaining < 0:
                        remaining = 0
                    rem_min = int(remaining // 60)
                    rem_sec = int(remaining % 60)
                    label.configure(text=self.loc[lang]["status_rem"].format(min=rem_min, sec=rem_sec), text_color="#10B981")
                    
                    total = task["duration_minutes"] * 60.0
                    ratio = max(0.0, min(1.0, remaining / total)) if total > 0.0 else 0.0
                    
                    if remaining < 60.0 or ratio < 0.2:
                        progress_color = "#EF4444" # Red
                    elif ratio < 0.6:
                        progress_color = "#F59E0B" # Yellow
                    else:
                        progress_color = "#10B981" # Green
                        
                    if pbar:
                        pbar.set(ratio)
                        pbar.configure(progress_color=progress_color)
                    if hglass_or_clock:
                        time_str = f"{rem_min:02d}:{rem_sec:02d}"
                        hglass_or_clock.set_progress(ratio, is_paused=False, color=progress_color, time_str=time_str)
                else:
                    repeat_str = ""
                    if task["repeat_days"]:
                        if len(task["repeat_days"]) == 7:
                            repeat_str = self.loc[lang]["repeat_everyday"]
                        elif set(task["repeat_days"]) == {1, 2, 3, 4, 5}:
                            repeat_str = self.loc[lang]["repeat_weekdays"]
                        elif set(task["repeat_days"]) == {6, 7}:
                            repeat_str = self.loc[lang]["repeat_weekends"]
                        else:
                            days_formatted = ",".join([self.loc[lang]["weekdays"][d-1] for d in task["repeat_days"]])
                            repeat_str = self.loc[lang]["repeat_days_fmt"].format(days=days_formatted)
                    else:
                        repeat_str = self.loc[lang]["repeat_oneoff"]
                    label.configure(text=self.loc[lang]["status_target"].format(time=task['alarm_time'], repeat=repeat_str), text_color="#10B981")
                    if pbar:
                        pbar.set(1.0)
                        pbar.configure(progress_color="#10B981")
                    if hglass_or_clock:
                        hglass_or_clock.set_progress(1.0, is_paused=False, color="#10B981")

    def update_gui_status(self):
        """Thread-safe UI polling loop (ticks once per second if window is viewable)."""
        if not self.root or not self.root.winfo_exists():
            self.status_loop_active = False
            return
            
        if not self.root.winfo_viewable():
            self.status_loop_active = True
            self.root.after(1000, self.update_gui_status)
            return
            
        self.status_loop_active = True
        self.tick_gui_status()
        self.root.after(1000, self.update_gui_status)

    def hide_window(self):
        if self.root:
            self.root.withdraw()
            self.status_loop_active = False

    def show_window(self, icon=None, item=None):
        if self.root:
            self.root.after(0, self._show_window_main_thread)

    def _show_window_main_thread(self):
        if self.root:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if not self.status_loop_active:
                self.update_gui_status()

    def exit_app(self, icon=None, item=None):
        print("[TimerApp] Gracefully exiting, saving final task state...")
        self.is_running = False
        
        # Save state right before terminating
        self.save_config()
        
        if self.tray_icon:
            self.tray_icon.stop()
            
        if self.root:
            self.root.after(0, self.root.destroy)

    def run_tray_icon(self):
        """Starts pystray resident system tray in background thread."""
        lang = self.current_lang
        menu = pystray.Menu(
            pystray.MenuItem(self.loc[lang]["tray_show"], self.show_window, default=True),
            pystray.MenuItem(self.loc[lang]["tray_pause"], self.global_pause_tray),
            pystray.MenuItem(self.loc[lang]["tray_resume"], self.global_resume_tray),
            pystray.MenuItem(self.loc[lang]["tray_exit"], self.exit_app)
        )
        self.tray_icon = pystray.Icon(
            "NativeLoopTimer",
            self.icon_img,
            self.loc[lang]["tray_title"],
            menu
        )
        self.tray_icon.run()

    def start(self):
        tray_thread = threading.Thread(target=self.run_tray_icon, daemon=True, name="SystemTrayThread")
        tray_thread.start()
        
        self.build_gui()
        self.root.mainloop()


if __name__ == "__main__":
    import socket
    import sys
    
    # Try to bind to localhost on a specific port to ensure single instance
    PORT = 49512
    try:
        instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        instance_socket.bind(('127.0.0.1', PORT))
        instance_socket.listen(1)
    except socket.error:
        # Another instance is already running!
        # Send a wake up signal to the existing instance
        try:
            wake_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            wake_socket.connect(('127.0.0.1', PORT))
            wake_socket.sendall(b"show")
            wake_socket.close()
        except Exception:
            pass
        sys.exit(0)
        
    app = TimerApp()
    
    # Start a thread to listen for wake-up requests from other instances
    def wake_listener():
        while True:
            try:
                conn, addr = instance_socket.accept()
                data = conn.recv(1024)
                if data == b"show":
                    app.show_window()
                conn.close()
            except Exception:
                break
                
    import threading
    listener_thread = threading.Thread(target=wake_listener, daemon=True, name="InstanceWakeListener")
    listener_thread.start()
    
    app.start()

