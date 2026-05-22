import os
import sys
import time
import threading
import winreg
import ctypes
from PIL import Image, ImageDraw
import pystray
import customtkinter as ctk

# Import Windows Runtime notification APIs
import winrt.windows.ui.notifications as win_notify
import winrt.windows.data.xml.dom as win_xml

# Import Windows GUI/Power API bindings for sleep/wake monitoring
import win32gui
import win32con

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
        # Register an internal Window Class for receiving power broadcast messages
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self.wnd_proc
        wc.lpszClassName = "NativeLoopTimerPowerMonitor"
        wc.hInstance = win32gui.GetModuleHandle(None)
        
        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = wc.lpszClassName
            
        # Create a hidden message-only window (HWND_MESSAGE) that uses 0% CPU
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
        
        # Enter the event-driven Windows Message Loop
        win32gui.PumpMessages()

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_POWERBROADCAST:
            # PBT_APMRESUMESUSPEND = 0x0007 (resuming after suspension)
            # PBT_APMRESUMEAUTOMATIC = 0x0012 (resuming automatically)
            if wparam in (0x0007, 0x0012):
                print("[PowerMonitor] System wake-up event detected!")
                # Run the callback on system resume
                self.on_resume_callback()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class TimerApp:
    def __init__(self):
        self.interval_minutes = 20.0
        self.message_text = "时间到了！请起来活动一下，喝杯水休息一会吧！"
        
        self.is_running = False
        self.target_time = 0.0
        self.timer_thread = None
        self.status_loop_active = False
        self.lock = threading.Lock()
        
        self.root = None
        self.tray_icon = None
        
        # Paths
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
        self.ico_path = os.path.join(self.app_dir, "app_icon.ico")
        self.png_path = os.path.join(self.app_dir, "app_icon.png")
        
        # Initialize
        self.app_id = "NativeLoopTimer"
        self.register_app_id()
        self.ensure_assets()
        
        # Start power monitor
        self.power_monitor = PowerMonitor(self.on_system_wake)

    def register_app_id(self):
        """Register the application under HKCU to authorize Toast notifications."""
        path = rf"Software\Classes\AppUserModelId\{self.app_id}"
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "原生通知循环定时器")
            winreg.CloseKey(key)
            
            # Set this process's explicit AppUserModelID
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(self.app_id)
            print("[TimerApp] AppUserModelID successfully registered.")
        except Exception as e:
            print(f"[TimerApp] Warning registering AUMID: {e}")

    def ensure_assets(self):
        """Programmatically generate a beautiful, modern multi-resolution icon."""
        if not os.path.exists(self.ico_path) or not os.path.exists(self.png_path):
            print("[TimerApp] Generating high-quality icon assets...")
            # Design a sleek radial gradient canvas
            size = 256
            img = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Draw premium dark gradient background
            for r in range(120, 0, -1):
                factor = r / 120.0
                # Interpolate from deep slate-blue to rich royal indigo
                color_r = int(20 * factor + 54 * (1.0 - factor))
                color_g = int(24 * factor + 86 * (1.0 - factor))
                color_b = int(72 * factor + 224 * (1.0 - factor))
                draw.ellipse([128 - r, 128 - r, 128 + r, 128 + r], fill=(color_r, color_g, color_b, 255))
                
            # Draw highly elegant timer dial ring
            draw.arc([48, 48, 208, 208], start=0, end=360, fill=(255, 255, 255, 210), width=10)
            
            # Draw minimal aesthetic clock hands (10:10 format)
            draw.line([128, 128, 85, 85], fill=(255, 255, 255, 240), width=8)  # Hour hand
            draw.line([128, 128, 175, 85], fill=(255, 80, 100, 255), width=6)  # Accent colored minute hand
            
            # Center core pin
            draw.ellipse([120, 120, 136, 136], fill=(255, 255, 255, 255))
            
            # Save files
            img.save(self.png_path, format="PNG")
            img.save(self.ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            
        self.icon_img = Image.open(self.png_path)

    def trigger_notification(self):
        """Creates and triggers an absolute native zero-focus stealing Windows Toast."""
        with self.lock:
            message = self.message_text
            
        try:
            # Windows native short-duration non-intrusive XML Schema
            xml_str = f"""
            <toast duration="short">
                <visual>
                    <binding template="ToastGeneric">
                        <text>循环定时器提醒</text>
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
            print(f"[TimerApp] Native Toast Notification delivered: '{message}'")
        except Exception as e:
            print(f"[TimerApp] Error displaying notification: {e}")

    def timer_loop(self):
        """Ultra-low power countdown checking mechanism."""
        while True:
            with self.lock:
                if not self.is_running:
                    break
                curr = time.time()
                target = self.target_time
                
            if curr >= target:
                # Trigger the Toast notification
                self.trigger_notification()
                
                # Instantly shift target to next alarm to avoid drift
                with self.lock:
                    interval_secs = self.interval_minutes * 60.0
                    # If heavily drifted (e.g. system suspended), align relative to current time
                    if curr - target > interval_secs:
                        self.target_time = curr + interval_secs
                    else:
                        self.target_time = target + interval_secs
                        
            time.sleep(0.5)

    def on_system_wake(self):
        """Power event wakeup callback for sleep compensation."""
        with self.lock:
            if not self.is_running:
                return
            curr = time.time()
            target = self.target_time
            
        if curr >= target:
            print("[TimerApp] System woke up and missed scheduled notification. Reissuing immediately.")
            self.trigger_notification()
            
            # Recalculate and reset next loop starting from this wakeup epoch
            with self.lock:
                self.target_time = curr + (self.interval_minutes * 60.0)

    def start_timer(self, minutes, text):
        """Set or update values and fire background loop thread."""
        with self.lock:
            self.interval_minutes = minutes
            self.message_text = text
            self.target_time = time.time() + (minutes * 60.0)
            self.is_running = True
            
        print(f"[TimerApp] Timer started for {minutes} min. Next alert: {time.strftime('%H:%M:%S', time.localtime(self.target_time))}")
        
        # Launch timer thread if not running
        if self.timer_thread is None or not self.timer_thread.is_alive():
            self.timer_thread = threading.Thread(target=self.timer_loop, daemon=True, name="TimerLoopThread")
            self.timer_thread.start()

    def stop_timer(self):
        with self.lock:
            self.is_running = False

    def build_gui(self):
        """Creates the state-of-the-art CustomTkinter user interface."""
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("原生循环定时器 - 设置")
        self.root.geometry("480x420")
        self.root.resizable(False, False)
        
        # Load window icon
        try:
            self.root.iconbitmap(self.ico_path)
        except Exception:
            pass
            
        # UI Styling Elements
        title_font = ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        info_font = ctk.CTkFont(family="Segoe UI", size=12)
        
        # Title Header
        title_label = ctk.CTkLabel(
            self.root, 
            text="⏰ Windows 原生循环定时器", 
            font=title_font,
            text_color="#60A5FA" # Sleek blue accent
        )
        title_label.pack(pady=(25, 5))
        
        subtitle_label = ctk.CTkLabel(
            self.root,
            text="超低功耗设计 · 绝对免打扰 · 自动休眠补偿",
            font=info_font,
            text_color="#9CA3AF"
        )
        subtitle_label.pack(pady=(0, 20))
        
        # Form Box
        form_frame = ctk.CTkFrame(self.root, corner_radius=10, fg_color="#1F2937")
        form_frame.pack(padx=30, fill="both", expand=True, pady=(0, 15))
        
        # Input 1: Time Interval
        time_label = ctk.CTkLabel(form_frame, text="循环时间 (分钟):", font=label_font, text_color="#E5E7EB")
        time_label.pack(anchor="w", padx=20, pady=(15, 2))
        
        self.time_entry = ctk.CTkEntry(
            form_frame, 
            placeholder_text="输入分钟数 (如 20 或 0.5)", 
            font=info_font,
            height=32,
            border_color="#4B5563"
        )
        self.time_entry.pack(fill="x", padx=20, pady=(0, 5))
        self.time_entry.insert(0, str(self.interval_minutes))
        
        # Input 2: Notification Message
        msg_label = ctk.CTkLabel(form_frame, text="提醒内容:", font=label_font, text_color="#E5E7EB")
        msg_label.pack(anchor="w", padx=20, pady=(10, 2))
        
        self.msg_entry = ctk.CTkEntry(
            form_frame, 
            placeholder_text="输入 Toast 显示的提醒内容", 
            font=info_font,
            height=32,
            border_color="#4B5563"
        )
        self.msg_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.msg_entry.insert(0, self.message_text)
        
        # Error Label
        self.error_label = ctk.CTkLabel(self.root, text="", font=info_font, text_color="#EF4444")
        self.error_label.pack()
        
        # Actions & Status Bottom Panel
        self.status_label = ctk.CTkLabel(
            self.root, 
            text="状态: 未运行", 
            font=label_font, 
            text_color="#9CA3AF"
        )
        self.status_label.pack(pady=5)
        
        self.start_btn = ctk.CTkButton(
            self.root,
            text="开始运行 (隐藏窗口)",
            command=self.on_start_clicked,
            font=label_font,
            height=40,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8"
        )
        self.start_btn.pack(pady=(5, 25), padx=30, fill="x")
        
        # Intercept Close Window (X) Event
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        # Start GUI status updates
        self.update_gui_status()

    def on_start_clicked(self):
        """Validate user inputs and run background loop."""
        time_str = self.time_entry.get().strip()
        msg_str = self.msg_entry.get().strip()
        
        if not time_str:
            self.error_label.configure(text="❌ 请输入循环时间！")
            return
            
        try:
            minutes = float(time_str)
            if minutes <= 0:
                raise ValueError()
        except ValueError:
            self.error_label.configure(text="❌ 时间必须是大于 0 的数字！")
            return
            
        if not msg_str:
            self.error_label.configure(text="❌ 请输入提醒内容！")
            return
            
        self.error_label.configure(text="")
        
        # Start/Update background timer state
        self.start_timer(minutes, msg_str)
        
        # Hide window immediately
        self.hide_window()

    def update_gui_status(self):
        """Thread-safe graphical interface polling method (runs every 1s when active)."""
        if not self.root or not self.root.winfo_exists() or not self.root.winfo_viewable():
            self.status_loop_active = False
            return
            
        self.status_loop_active = True
        
        with self.lock:
            is_running = self.is_running
            target = self.target_time
            
        if is_running:
            curr = time.time()
            remaining = target - curr
            if remaining < 0:
                remaining = 0
                
            rem_min = int(remaining // 60)
            rem_sec = int(remaining % 60)
            target_str = time.strftime("%H:%M:%S", time.localtime(target))
            
            self.status_label.configure(
                text=f"状态: 正在后台运行\n下次提醒: {target_str} (剩余 {rem_min}分{rem_sec}秒)",
                text_color="#10B981" # Green
            )
            self.start_btn.configure(text="更新配置并重新运行")
        else:
            self.status_label.configure(
                text="状态: 未运行",
                text_color="#9CA3AF" # Grey
            )
            self.start_btn.configure(text="开始运行 (隐藏窗口)")
            
        self.root.after(1000, self.update_gui_status)

    def hide_window(self):
        """Hides settings GUI. Taskbar entry is completely removed."""
        if self.root:
            self.root.withdraw()
            self.status_loop_active = False

    def show_window(self, icon=None, item=None):
        """Safely wakes settings window from pystray thread."""
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
        """Exits whole application cleanly."""
        print("[TimerApp] Exiting App...")
        self.stop_timer()
        
        if self.tray_icon:
            self.tray_icon.stop()
            
        if self.root:
            self.root.after(0, self.root.destroy)

    def run_tray_icon(self):
        """Starts pystray resident system tray in background."""
        menu = pystray.Menu(
            pystray.MenuItem("显示设置 (Settings)", self.show_window, default=True),
            pystray.MenuItem("退出 (Exit)", self.exit_app)
        )
        self.tray_icon = pystray.Icon(
            "NativeLoopTimer",
            self.icon_img,
            "原生通知循环定时器",
            menu
        )
        self.tray_icon.run()

    def start(self):
        # Start System Tray in background thread
        tray_thread = threading.Thread(target=self.run_tray_icon, daemon=True, name="SystemTrayThread")
        tray_thread.start()
        
        # Open Tkinter GUI on main thread
        self.build_gui()
        self.root.mainloop()


if __name__ == "__main__":
    app = TimerApp()
    app.start()
