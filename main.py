import os
import sys
import time
import threading
import winreg
import ctypes
import json
import uuid
import re
from PIL import Image, ImageDraw
import pystray
import customtkinter as ctk
import tkinter as tk

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
        
        # Paths
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
        self.ico_path = os.path.join(self.app_dir, "app_icon.ico")
        self.png_path = os.path.join(self.app_dir, "app_icon.png")
        
        # Initialize
        self.app_id = "NativeLoopTimer"
        self.register_app_id()
        self.ensure_assets()
        
        # Load tasks from config.json and compensate missed alarms
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
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "多任务原生定时中心")
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
            return []
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                tasks = data.get("tasks", [])
                
                # Normalize types to prevent JSON schema compatibility issues
                for task in tasks:
                    task["is_paused"] = bool(task.get("is_paused", False))
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
            return []

    def save_config(self):
        """Saves current memory task configurations into local config.json."""
        config_path = os.path.join(self.app_dir, "config.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"tasks": self.tasks}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TimerApp] Error saving config: {e}")

    def trigger_merged_notification(self, missed_tasks):
        """Pushes a single native Toast displaying all missed alerts in one visual card."""
        if not missed_tasks:
            return
            
        try:
            if len(missed_tasks) == 1:
                title = "定时中心提醒"
                message = missed_tasks[0]["name"]
            else:
                title = f"错过了 {len(missed_tasks)} 个提醒"
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
            </toast>
            """
            xml_doc = win_xml.XmlDocument()
            xml_doc.load_xml(xml_str)
            
            notifier = win_notify.ToastNotificationManager.create_toast_notifier_with_id(self.app_id)
            toast = win_notify.ToastNotification(xml_doc)
            notifier.show(toast)
            print(f"[TimerApp] Toast delivered: '{title}' - '{message}'")
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
        self.root.title("多任务原生定时中心")
        self.root.geometry("520x600")
        self.root.resizable(True, True)
        self.root.minsize(520, 600)
        
        try:
            self.root.iconbitmap(self.ico_path)
        except Exception:
            pass
            
        title_font = ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        info_font = ctk.CTkFont(family="Segoe UI", size=12)
        
        # Global Scroll Container
        self.main_scroll_container = ctk.CTkScrollableFrame(
            self.root,
            fg_color="#111827",
            corner_radius=0
        )
        self.main_scroll_container.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Bind canvas configuration to auto-adjust scrollbar visibility
        self.main_scroll_container._parent_canvas.bind(
            "<Configure>", 
            lambda e: self.root.after(10, self.adjust_scrollbar_visibility), 
            add="+"
        )
        
        # Header Box
        title_label = ctk.CTkLabel(
            self.main_scroll_container, 
            text="⏰ 多任务原生定时中心", 
            font=title_font,
            text_color="#60A5FA"
        )
        title_label.pack(pady=(20, 3))
        
        subtitle_label = ctk.CTkLabel(
            self.main_scroll_container,
            text="独立多任务并发 · 暂停/恢复管理 · 系统级防丢自唤醒",
            font=info_font,
            text_color="#9CA3AF"
        )
        subtitle_label.pack(pady=(0, 15))
        
        # Main Creation Form Card
        form_frame = ctk.CTkFrame(self.main_scroll_container, corner_radius=10, fg_color="#1F2937")
        form_frame.pack(padx=30, fill="x", pady=(0, 15))
        
        # Tab selection: Segmented Button
        self.segmented_button = ctk.CTkSegmentedButton(
            form_frame,
            values=["⏳ 定时器", "⏰ 闹钟"],
            command=self.on_segmented_btn_changed,
            font=label_font,
            height=32
        )
        self.segmented_button.pack(padx=20, pady=(15, 5), fill="x")
        self.segmented_button.set("⏳ 定时器")
        
        # Sub-form 1: Timer Fields
        self.timer_fields_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        self.timer_fields_frame.pack(fill="x", padx=20, pady=5)
        
        time_label = ctk.CTkLabel(self.timer_fields_frame, text="倒计时时间 (分钟):", font=label_font, text_color="#E5E7EB")
        time_label.pack(anchor="w", pady=(5, 2))
        
        self.time_entry = ctk.CTkEntry(
            self.timer_fields_frame, 
            placeholder_text="输入分钟数 (如 20 或 0.5)", 
            font=info_font,
            height=32,
            border_color="#4B5563"
        )
        self.time_entry.pack(fill="x", pady=(0, 5))
        self.time_entry.insert(0, "20.0")
        
        self.timer_loop_var = ctk.BooleanVar(value=True)
        self.timer_loop_cb = ctk.CTkCheckBox(
            self.timer_fields_frame,
            text="触发后自动循环计时",
            variable=self.timer_loop_var,
            font=info_font,
            checkbox_width=18,
            checkbox_height=18
        )
        self.timer_loop_cb.pack(anchor="w", pady=5)
        
        # Sub-form 2: Alarm Fields (hidden initially)
        self.alarm_fields_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        
        alarm_label = ctk.CTkLabel(self.alarm_fields_frame, text="闹钟时间:", font=label_font, text_color="#E5E7EB")
        alarm_label.pack(anchor="w", pady=(5, 2))
        
        entry_row = ctk.CTkFrame(self.alarm_fields_frame, fg_color="transparent")
        entry_row.pack(fill="x", pady=(0, 5))
        
        self.alarm_hour_entry = ctk.CTkEntry(
            entry_row,
            width=60,
            placeholder_text="时",
            font=info_font,
            height=32,
            border_color="#4B5563",
            justify="center"
        )
        self.alarm_hour_entry.pack(side="left")
        
        colon_label = ctk.CTkLabel(
            entry_row, 
            text=":", 
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), 
            text_color="#9CA3AF"
        )
        colon_label.pack(side="left", padx=8)
        
        self.alarm_minute_entry = ctk.CTkEntry(
            entry_row,
            width=60,
            placeholder_text="分",
            font=info_font,
            height=32,
            border_color="#4B5563",
            justify="center"
        )
        self.alarm_minute_entry.pack(side="left")
        
        # Key bindings for auto-tabbing and keyboard focus management
        self.alarm_hour_entry.bind("<KeyRelease>", self.on_hour_keyrelease)
        self.alarm_hour_entry.bind("<KeyPress>", self.on_hour_keypress)
        self.alarm_minute_entry.bind("<KeyPress>", self.on_minute_keypress)
        self.alarm_hour_entry.bind("<Return>", lambda e: self.on_start_clicked())
        self.alarm_minute_entry.bind("<Return>", lambda e: self.on_start_clicked())
        
        repeat_label = ctk.CTkLabel(self.alarm_fields_frame, text="重复周期 (不勾选为单次):", font=label_font, text_color="#E5E7EB")
        repeat_label.pack(anchor="w", pady=(5, 2))
        
        self.everyday_var = ctk.BooleanVar(value=False)
        self.everyday_cb = ctk.CTkCheckBox(
            self.alarm_fields_frame,
            text="每天 (一至日)",
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
        weekdays_label = ["一", "二", "三", "四", "五", "六", "日"]
        for i, day in enumerate(weekdays_label):
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(
                days_frame,
                text=day,
                variable=var,
                width=40,
                checkbox_width=16,
                checkbox_height=16,
                font=info_font,
                border_width=2,
                command=self.on_day_changed
            )
            cb.pack(side="left", padx=1)
            self.repeat_vars.append((i + 1, var))
            
        # Common Input: Message Text
        msg_label = ctk.CTkLabel(form_frame, text="提醒显示内容:", font=label_font, text_color="#E5E7EB")
        msg_label.pack(anchor="w", padx=20, pady=(5, 2))
        
        self.msg_entry = ctk.CTkEntry(
            form_frame, 
            placeholder_text="输入 Toast 通知要显示的文本内容", 
            font=info_font,
            height=32,
            border_color="#4B5563"
        )
        self.msg_entry.pack(fill="x", padx=20, pady=(0, 10))
        self.msg_entry.insert(0, "时间到了！请起来活动一下，喝杯水休息一会吧！")
        
        # Submit Button
        self.start_btn = ctk.CTkButton(
            form_frame,
            text="➕ 添加并启动新任务",
            command=self.on_start_clicked,
            font=label_font,
            height=36,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8"
        )
        self.start_btn.pack(padx=20, fill="x", pady=(5, 15))
        
        # Error / Validation Label
        self.error_label = ctk.CTkLabel(self.main_scroll_container, text="", font=info_font, text_color="#EF4444")
        self.error_label.pack(pady=(0, 5))
        
        # Middle List Section Label & Controls
        controls_frame = ctk.CTkFrame(self.main_scroll_container, fg_color="transparent")
        controls_frame.pack(padx=30, fill="x", pady=(0, 5))
        
        global_pause_btn = ctk.CTkButton(
            controls_frame,
            text="⏸ 暂停全部",
            font=info_font,
            height=26,
            fg_color="#374151",
            hover_color="#4B5563",
            command=self.global_pause
        )
        global_pause_btn.pack(side="left", padx=(0, 5))
        
        global_resume_btn = ctk.CTkButton(
            controls_frame,
            text="▶ 恢复全部",
            font=info_font,
            height=26,
            fg_color="#10B981",
            hover_color="#059669",
            command=self.global_resume
        )
        global_resume_btn.pack(side="left", padx=5)
        
        # Standard active tasks container inside the global scroll frame (Option A)
        self.list_title_label = ctk.CTkLabel(
            self.main_scroll_container,
            text="⏳ 当前活动任务与闹钟列表",
            font=label_font,
            text_color="#E5E7EB"
        )
        self.list_title_label.pack(padx=30, anchor="w", pady=(10, 5))
        
        self.task_list_frame = ctk.CTkFrame(
            self.main_scroll_container,
            fg_color="transparent"
        )
        self.task_list_frame.pack(padx=30, fill="x", expand=True, pady=(0, 20))
        
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        # Initial Render & Loop Waking
        self.render_task_list()
        self.update_gui_status()

    def on_segmented_btn_changed(self, value):
        """Smoothly toggles sub-form inputs inside the frame."""
        if value == "⏳ 定时器":
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
            canvas = self.main_scroll_container._parent_canvas
            scrollbar = self.main_scroll_container._scrollbar
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                content_height = bbox[3] - bbox[1]
                canvas_height = canvas.winfo_height()
                if content_height <= canvas_height:
                    scrollbar.grid_forget()
                else:
                    scrollbar.grid(row=0, column=1, sticky="ns", padx=(self.main_scroll_container._scrollbar_padx, 0))
        except Exception as e:
            print(f"[Scrollbar] Error adjusting scrollbar: {e}")

    def on_start_clicked(self):
        """Validates inputs, appends a new task profile, and saves config."""
        current_tab = self.segmented_button.get()
        name_str = self.msg_entry.get().strip()
        if not name_str:
            self.error_label.configure(text="❌ 请输入提醒内容！", text_color="#EF4444")
            return
            
        if current_tab == "⏳ 定时器":
            time_str = self.time_entry.get().strip()
            minutes = self.validate_timer_duration(time_str)
            if minutes is None:
                self.error_label.configure(text="❌ 循环时间必须是大于 0 的数字！", text_color="#EF4444")
                return
                
            is_loop = self.timer_loop_var.get()
            new_task = {
                "id": str(uuid.uuid4()),
                "type": "timer",
                "name": name_str,
                "duration_minutes": minutes,
                "is_auto_loop": is_loop,
                "is_paused": False,
                "created_at": time.time(),
                "target_time": time.time() + (minutes * 60.0),
                "remaining_seconds": minutes * 60.0
            }
        else: # ⏰ 闹钟
            h_raw = self.alarm_hour_entry.get().strip()
            m_raw = self.alarm_minute_entry.get().strip()
            alarm_time = self.validate_alarm_time(h_raw, m_raw)
            if alarm_time is None:
                self.error_label.configure(text="❌ 闹钟时间格式无效！在小时和分钟框输入数字即可！", text_color="#EF4444")
                return
                
            repeat_days = []
            for day_num, var in self.repeat_vars:
                if var.get():
                    repeat_days.append(day_num)
                    
            target_epoch = calculate_next_alarm(alarm_time, repeat_days)
            new_task = {
                "id": str(uuid.uuid4()),
                "type": "alarm",
                "name": name_str,
                "alarm_time": alarm_time,
                "repeat_days": repeat_days,
                "is_paused": False,
                "is_completed_today": False,
                "target_time": target_epoch
            }
            
        with self.lock:
            self.tasks.append(new_task)
            
        self.save_config()
        
        # Display green success text
        self.error_label.configure(text="✓ 任务添加并启动成功！", text_color="#10B981")
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
        self.msg_entry.delete(0, 'end')
        self.msg_entry.insert(0, "时间到了！请起来活动一下，喝杯水休息一会吧！")
        
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
        
        with self.lock:
            tasks_copy = list(self.tasks)
            
        if not tasks_copy:
            empty_label = ctk.CTkLabel(
                self.task_list_frame,
                text="暂无运行中的定时任务，请在上方添加！",
                font=ctk.CTkFont(family="Segoe UI", size=13),
                text_color="#9CA3AF"
            )
            empty_label.pack(pady=40)
            return
            
        for task in tasks_copy:
            task_id = task["id"]
            
            # Card frame container
            card = ctk.CTkFrame(self.task_list_frame, fg_color="#1F2937", corner_radius=8, height=45)
            card.pack(fill="x", padx=5, pady=4)
            
            card.grid_columnconfigure(0, weight=0) # Badge
            card.grid_columnconfigure(1, weight=1) # Icon + Name
            card.grid_columnconfigure(2, weight=1) # Dynamic Timer Display
            card.grid_columnconfigure(3, weight=0) # Controls: Pause
            card.grid_columnconfigure(4, weight=0) # Controls: Trash
            
            # Status Indicator LED
            status_color = "#10B981" if not task["is_paused"] else "#F59E0B"
            status_dot = ctk.CTkLabel(card, text="●", text_color=status_color, font=("Segoe UI", 16))
            status_dot.grid(row=0, column=0, padx=(12, 6), pady=8)
            self.task_status_badges[task_id] = status_dot
            
            # Name and Type Badge
            icon = "⏳" if task["type"] == "timer" else "⏰"
            name_text = task["name"]
            if len(name_text) > 12:
                name_text = name_text[:10] + "..."
            name_label = ctk.CTkLabel(
                card,
                text=f"{icon} {name_text}",
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color="#E5E7EB",
                anchor="w"
            )
            name_label.grid(row=0, column=1, padx=5, pady=8, sticky="w")
            
            # Clock Countdown Label
            time_label = ctk.CTkLabel(
                card,
                text="等待中...",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color="#9CA3AF",
                anchor="w"
            )
            time_label.grid(row=0, column=2, padx=5, pady=8, sticky="w")
            self.task_labels[task_id] = time_label
            
            # Play/Pause Icon trigger
            btn_text = "⏸" if not task["is_paused"] else "▶"
            btn_fg = "#374151" if not task["is_paused"] else "#10B981"
            pause_btn = ctk.CTkButton(
                card,
                text=btn_text,
                width=28,
                height=28,
                fg_color=btn_fg,
                hover_color="#4B5563",
                corner_radius=6,
                command=lambda tid=task_id: self.toggle_task(tid)
            )
            pause_btn.grid(row=0, column=3, padx=4, pady=8)
            
            # Trash Icon trigger
            delete_btn = ctk.CTkButton(
                card,
                text="🗑",
                width=28,
                height=28,
                fg_color="#374151",
                hover_color="#EF4444",
                corner_radius=6,
                command=lambda tid=task_id: self.delete_task(tid)
            )
            delete_btn.grid(row=0, column=4, padx=(4, 12), pady=8)
            
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
        for task in tasks_copy:
            task_id = task["id"]
            if task_id not in self.task_labels:
                continue
                
            label = self.task_labels[task_id]
            if task["is_paused"]:
                if task["type"] == "timer":
                    rem = task["remaining_seconds"]
                    rem_min = int(rem // 60)
                    rem_sec = int(rem % 60)
                    label.configure(text=f"暂停 (余 {rem_min}分{rem_sec}秒)", text_color="#F59E0B")
                else:
                    label.configure(text="已暂停", text_color="#F59E0B")
            else:
                if task["type"] == "timer":
                    remaining = task["target_time"] - curr
                    if remaining < 0:
                        remaining = 0
                    rem_min = int(remaining // 60)
                    rem_sec = int(remaining % 60)
                    label.configure(text=f"剩余: {rem_min}分{rem_sec}秒", text_color="#10B981")
                else:
                    repeat_str = ""
                    if task["repeat_days"]:
                        if len(task["repeat_days"]) == 7:
                            repeat_str = " (每天)"
                        elif set(task["repeat_days"]) == {1, 2, 3, 4, 5}:
                            repeat_str = " (工作日)"
                        elif set(task["repeat_days"]) == {6, 7}:
                            repeat_str = " (周末)"
                        else:
                            repeat_str = f" (周{','.join(map(str, task['repeat_days']))})"
                    else:
                        repeat_str = " (单次)"
                    label.configure(text=f"目标: {task['alarm_time']}{repeat_str}", text_color="#10B981")

    def update_gui_status(self):
        """Thread-safe UI polling loop (ticks once per second if window is viewable)."""
        if not self.root or not self.root.winfo_exists() or not self.root.winfo_viewable():
            self.status_loop_active = False
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
        menu = pystray.Menu(
            pystray.MenuItem("显示设置 (Settings)", self.show_window, default=True),
            pystray.MenuItem("全局暂停所有 (Pause All)", self.global_pause_tray),
            pystray.MenuItem("全局恢复所有 (Resume All)", self.global_resume_tray),
            pystray.MenuItem("退出 (Exit)", self.exit_app)
        )
        self.tray_icon = pystray.Icon(
            "NativeLoopTimer",
            self.icon_img,
            "多任务原生定时中心",
            menu
        )
        self.tray_icon.run()

    def start(self):
        tray_thread = threading.Thread(target=self.run_tray_icon, daemon=True, name="SystemTrayThread")
        tray_thread.start()
        
        self.build_gui()
        self.root.mainloop()


if __name__ == "__main__":
    app = TimerApp()
    app.start()
