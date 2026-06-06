import datetime as _dt
import html
import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path


APP_ID = "NativeLoopTimer"
DEFAULT_SOUND = "C:/Windows/Media/Windows Default.wav"
DEFAULT_GROUP = {"zh": "默认", "en": "Default"}
DEFAULT_MESSAGE = {
    "zh": "时间到了！请起来活动一下，喝杯水休息一会吧！",
    "en": "Time's up! Please get up, stretch, drink some water and take a break!",
}
SOUND_OPTIONS = {
    "zh": {
        "🔔 经典闹铃 (Classic Alarm)": "C:/Windows/Media/Alarm01.wav",
        "🔔 晨光风铃 (Morning Chimes)": "C:/Windows/Media/chimes.wav",
        "🔔 静谧和弦 (Serene Chord)": "C:/Windows/Media/chord.wav",
        "🔔 温馨叮咚 (Warm Ding)": "C:/Windows/Media/ding.wav",
        "🔔 凯旋之声 (Tada Fanfare)": "C:/Windows/Media/tada.wav",
        "🔔 电子警报 (Digital Alarm)": "C:/Windows/Media/Alarm03.wav",
        "🔔 系统默认 (System Default)": DEFAULT_SOUND,
    },
    "en": {
        "🔔 Classic Alarm": "C:/Windows/Media/Alarm01.wav",
        "🔔 Morning Chimes": "C:/Windows/Media/chimes.wav",
        "🔔 Serene Chord": "C:/Windows/Media/chord.wav",
        "🔔 Warm Ding": "C:/Windows/Media/ding.wav",
        "🔔 Tada Fanfare": "C:/Windows/Media/tada.wav",
        "🔔 Digital Alarm": "C:/Windows/Media/Alarm03.wav",
        "🔔 System Default": DEFAULT_SOUND,
    },
}


def configure_stdio():
    """Keep JSON IPC UTF-8 clean in PyInstaller console builds on Windows."""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _now() -> float:
    return time.time()


def _as_float(value, default=0.0) -> float:
    try:
        result = float(value)
        if result != result:
            return default
        return result
    except (TypeError, ValueError):
        return default


def _as_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _safe_str(value, default="") -> str:
    if value is None:
        return default
    return str(value)


def _clean_repeat_days(value):
    days = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            try:
                day = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= day <= 7 and day not in days:
                days.append(day)
    return sorted(days)


def calculate_next_alarm(alarm_time_str, repeat_days, from_time=None):
    """Return the next epoch timestamp for an HH:MM alarm."""
    base = _dt.datetime.fromtimestamp(from_time if from_time is not None else _now())
    try:
        hour, minute = [int(part) for part in str(alarm_time_str).split(":", 1)]
    except Exception:
        hour, minute = 8, 30

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days = _clean_repeat_days(repeat_days)

    if not days:
        if target <= base:
            target += _dt.timedelta(days=1)
        return target.timestamp()

    for offset in range(8):
        candidate = target + _dt.timedelta(days=offset)
        if candidate.isoweekday() in days and candidate > base:
            return candidate.timestamp()

    return (target + _dt.timedelta(days=1)).timestamp()


class PowerMonitor:
    """Optional Windows sleep/wake monitor used by the backend service."""

    def __init__(self, on_resume_callback):
        self.on_resume_callback = on_resume_callback
        self.thread = threading.Thread(target=self._run, daemon=True, name="PowerMonitorThread")
        self.thread.start()

    def _run(self):
        try:
            import win32con
            import win32gui
        except Exception:
            return

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "NativeLoopTimerBackendPowerMonitor"
        wc.hInstance = win32gui.GetModuleHandle(None)

        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = wc.lpszClassName

        try:
            win32gui.CreateWindowEx(
                0,
                class_atom,
                "NativeLoopTimerBackendPowerMonitor",
                0,
                0,
                0,
                0,
                0,
                win32con.HWND_MESSAGE,
                0,
                wc.hInstance,
                None,
            )
            win32gui.PumpMessages()
        except Exception:
            return

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            import win32con
            import win32gui
        except Exception:
            return 0

        if msg == win32con.WM_POWERBROADCAST and wparam in (0x0007, 0x0012):
            self.on_resume_callback()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class NativeLoopBackend:
    def __init__(self, config_dir=None):
        self.app_dir = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
        configured_dir = config_dir or os.environ.get("NATIVE_LOOP_TIMER_CONFIG_DIR")
        self.uses_custom_config_dir = configured_dir is not None
        self.config_dir = Path(
            configured_dir or (Path(os.environ["APPDATA"]) / APP_ID if os.environ.get("APPDATA") else self.app_dir)
        )
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "config.json"
        self.local_config_path = self.app_dir / "config.json"
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.command_queue = queue.Queue()
        self.running = True
        self.parent_closed = False
        self.current_lang = "zh"
        self.tasks = []
        self.last_snapshot_at = 0.0
        self.notify_disabled = os.environ.get("NATIVE_LOOP_TIMER_DISABLE_NOTIFY") == "1"
        self.power_monitor = None

        self._migrate_local_config()
        self.load_config()
        self._register_app_id()
        if os.environ.get("NATIVE_LOOP_TIMER_DISABLE_POWER_MONITOR") != "1":
            self.power_monitor = PowerMonitor(lambda: self.check_due_tasks(force_save=True))

    def _migrate_local_config(self):
        if self.uses_custom_config_dir:
            return
        if self.config_path.exists() or not self.local_config_path.exists():
            return
        try:
            self.config_path.write_bytes(self.local_config_path.read_bytes())
        except Exception as exc:
            self.emit_error(f"Config migration failed: {exc}")

    def _register_app_id(self):
        if self.notify_disabled or os.name != "nt":
            return
        try:
            import ctypes
            import winreg

            path = rf"Software\Classes\AppUserModelId\{APP_ID}"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "NativeLoopTimer")
            winreg.CloseKey(key)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    def emit(self, packet):
        packet.setdefault("serverTime", _now())
        with self.output_lock:
            sys.stdout.write(json.dumps(packet, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def emit_error(self, message, request_id=None):
        packet = {"event": "error", "message": str(message)}
        if request_id is not None:
            packet["requestId"] = request_id
        self.emit(packet)

    def emit_state(self, request_id=None):
        with self.state_lock:
            packet = {
                "event": "stateSnapshot",
                "language": self.current_lang,
                "tasks": [dict(task) for task in self.tasks],
                "soundOptions": SOUND_OPTIONS,
                "configPath": str(self.config_path),
            }
        if request_id is not None:
            packet["requestId"] = request_id
        self.emit(packet)
        self.last_snapshot_at = _now()

    def load_config(self):
        if not self.config_path.exists():
            self.current_lang = "zh"
            self.tasks = []
            return

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.current_lang = "zh"
            self.tasks = []
            self.emit_error(f"Config load failed: {exc}")
            return

        lang = data.get("language", "zh")
        self.current_lang = lang if lang in ("zh", "en") else "zh"
        raw_tasks = data.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raw_tasks = []

        now = _now()
        normalized = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                continue
            task = self.normalize_task(raw, now)
            if task is not None:
                normalized.append(task)
        self.tasks = normalized

    def save_config(self):
        with self.state_lock:
            payload = {
                "tasks": [dict(task) for task in self.tasks],
                "language": self.current_lang,
            }
        temp_path = self.config_path.with_suffix(".json.tmp")
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.config_path)
        except Exception as exc:
            self.emit_error(f"Config save failed: {exc}")

    def normalize_task(self, raw, now=None):
        now = now if now is not None else _now()
        task_type = _safe_str(raw.get("type"), "timer").lower()
        if task_type not in {"timer", "alarm"}:
            return None

        created_at = _as_float(raw.get("created_at"), now)
        task = {
            "id": _safe_str(raw.get("id"), str(uuid.uuid4())),
            "type": task_type,
            "name": _safe_str(raw.get("name"), DEFAULT_MESSAGE[self.current_lang]).strip()
            or DEFAULT_MESSAGE[self.current_lang],
            "group": _safe_str(raw.get("group"), DEFAULT_GROUP[self.current_lang]).strip()
            or DEFAULT_GROUP[self.current_lang],
            "sound_path": _safe_str(raw.get("sound_path"), DEFAULT_SOUND),
            "is_paused": _as_bool(raw.get("is_paused"), False),
            "created_at": created_at,
            "order": _as_float(raw.get("order"), created_at),
        }

        if task_type == "timer":
            duration = _as_float(raw.get("duration_minutes"), 20.0)
            if duration <= 0:
                duration = 20.0
            total = duration * 60.0
            target_time = _as_float(raw.get("target_time"), now + total)
            remaining = _as_float(raw.get("remaining_seconds"), max(0.0, target_time - now))
            if task["is_paused"]:
                remaining = max(0.0, min(total, remaining if remaining > 0 else total))
            elif target_time <= 0:
                target_time = now + max(0.0, min(total, remaining if remaining > 0 else total))
            task.update(
                {
                    "duration_minutes": duration,
                    "is_auto_loop": _as_bool(raw.get("is_auto_loop"), True),
                    "target_time": target_time,
                    "remaining_seconds": max(0.0, remaining),
                }
            )
        else:
            alarm_time = self.validate_alarm_time(_safe_str(raw.get("alarm_time"), "08:30")) or "08:30"
            repeat_days = _clean_repeat_days(raw.get("repeat_days", []))
            target_time = _as_float(raw.get("target_time"), 0.0)
            if target_time <= 0:
                target_time = calculate_next_alarm(alarm_time, repeat_days, now)
            task.update(
                {
                    "alarm_time": alarm_time,
                    "repeat_days": repeat_days,
                    "target_time": target_time,
                }
            )
        return task

    @staticmethod
    def validate_alarm_time(value):
        try:
            parts = str(value).strip().replace("：", ":").split(":")
            if len(parts) != 2:
                return None
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            return None

    def listen_stdin(self):
        while self.running:
            line = sys.stdin.readline()
            if not line:
                self.parent_closed = True
                self.running = False
                break
            line = line.strip()
            if not line:
                continue
            try:
                packet = json.loads(line)
            except json.JSONDecodeError as exc:
                self.emit_error(f"Invalid JSON command: {exc}")
                continue
            self.command_queue.put(packet)

    def run(self):
        threading.Thread(target=self.listen_stdin, daemon=True, name="IPCInputThread").start()
        self.check_due_tasks(force_save=True)
        self.emit_state()

        while self.running:
            self.process_pending_commands()
            self.check_due_tasks()
            if _now() - self.last_snapshot_at >= 1.0:
                self.emit_state()
            time.sleep(0.2)

        self.save_config()

    def process_pending_commands(self):
        while self.running:
            try:
                packet = self.command_queue.get_nowait()
            except queue.Empty:
                return
            self.handle_command(packet)

    def handle_command(self, packet):
        command = packet.get("command") or packet.get("action")
        request_id = packet.get("requestId")
        payload = packet.get("payload")
        if payload is None:
            payload = packet
        if not command:
            self.emit_error("Missing command", request_id)
            return

        try:
            if command == "loadState":
                self.emit_state(request_id)
            elif command == "createTask":
                self.create_task(payload)
                self.save_config()
                self.emit_state(request_id)
            elif command == "updateTask":
                self.update_task(payload)
                self.save_config()
                self.emit_state(request_id)
            elif command == "deleteTask":
                self.delete_task(payload.get("id"))
                self.save_config()
                self.emit_state(request_id)
            elif command == "pauseTask":
                self.pause_task(payload.get("id"))
                self.save_config()
                self.emit_state(request_id)
            elif command == "resumeTask":
                self.resume_task(payload.get("id"))
                self.save_config()
                self.emit_state(request_id)
            elif command == "resetTask":
                self.reset_task(payload.get("id"))
                self.save_config()
                self.emit_state(request_id)
            elif command == "pauseAll":
                self.pause_all()
                self.save_config()
                self.emit_state(request_id)
            elif command == "resumeAll":
                self.resume_all()
                self.save_config()
                self.emit_state(request_id)
            elif command == "reorderTasks":
                self.reorder_tasks(payload.get("ids", []))
                self.save_config()
                self.emit_state(request_id)
            elif command == "setLanguage":
                self.set_language(payload.get("language"))
                self.save_config()
                self.emit_state(request_id)
            elif command == "shutdown":
                self.running = False
                self.emit({"event": "shutdown", "requestId": request_id})
            else:
                self.emit_error(f"Unknown command: {command}", request_id)
        except Exception as exc:
            self.emit_error(str(exc), request_id)

    def find_task(self, task_id):
        for task in self.tasks:
            if task.get("id") == task_id:
                return task
        raise KeyError(f"Task not found: {task_id}")

    def create_task(self, payload):
        task_type = _safe_str(payload.get("type"), "timer").lower()
        if task_type not in {"timer", "alarm"}:
            raise ValueError("Task type must be timer or alarm")

        now = _now()
        base = {
            "id": _safe_str(payload.get("id"), str(uuid.uuid4())),
            "type": task_type,
            "name": _safe_str(payload.get("name"), DEFAULT_MESSAGE[self.current_lang]).strip()
            or DEFAULT_MESSAGE[self.current_lang],
            "group": _safe_str(payload.get("group"), DEFAULT_GROUP[self.current_lang]).strip()
            or DEFAULT_GROUP[self.current_lang],
            "sound_path": _safe_str(payload.get("sound_path"), DEFAULT_SOUND),
            "is_paused": False,
            "created_at": now,
            "order": now,
        }

        if task_type == "timer":
            duration = _as_float(payload.get("duration_minutes"), 20.0)
            if duration <= 0:
                raise ValueError("Timer duration must be greater than zero")
            total = duration * 60.0
            base.update(
                {
                    "duration_minutes": duration,
                    "is_auto_loop": _as_bool(payload.get("is_auto_loop"), True),
                    "target_time": now + total,
                    "remaining_seconds": total,
                }
            )
        else:
            alarm_time = self.validate_alarm_time(payload.get("alarm_time"))
            if alarm_time is None:
                raise ValueError("Invalid alarm time")
            repeat_days = _clean_repeat_days(payload.get("repeat_days", []))
            base.update(
                {
                    "alarm_time": alarm_time,
                    "repeat_days": repeat_days,
                    "target_time": calculate_next_alarm(alarm_time, repeat_days, now),
                }
            )

        with self.state_lock:
            self.tasks.append(base)
        self.emit({"event": "taskUpdated", "task": dict(base)})

    def update_task(self, payload):
        task_id = payload.get("id")
        now = _now()
        with self.state_lock:
            task = self.find_task(task_id)
            for key in ("name", "group", "sound_path"):
                if key in payload:
                    task[key] = _safe_str(payload.get(key), task.get(key, "")).strip() or task.get(key, "")

            if task["type"] == "timer":
                if "is_auto_loop" in payload:
                    task["is_auto_loop"] = _as_bool(payload.get("is_auto_loop"), task["is_auto_loop"])
                if "duration_minutes" in payload:
                    duration = _as_float(payload.get("duration_minutes"), task["duration_minutes"])
                    if duration <= 0:
                        raise ValueError("Timer duration must be greater than zero")
                    task["duration_minutes"] = duration
                    task["remaining_seconds"] = duration * 60.0
                    if not task["is_paused"]:
                        task["target_time"] = now + task["remaining_seconds"]
            else:
                changed = False
                if "alarm_time" in payload:
                    alarm_time = self.validate_alarm_time(payload.get("alarm_time"))
                    if alarm_time is None:
                        raise ValueError("Invalid alarm time")
                    changed = changed or alarm_time != task["alarm_time"]
                    task["alarm_time"] = alarm_time
                if "repeat_days" in payload:
                    repeat_days = _clean_repeat_days(payload.get("repeat_days"))
                    changed = changed or repeat_days != task["repeat_days"]
                    task["repeat_days"] = repeat_days
                if changed and not task["is_paused"]:
                    task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"], now)
            updated = dict(task)
        self.emit({"event": "taskUpdated", "task": updated})

    def delete_task(self, task_id):
        with self.state_lock:
            before = len(self.tasks)
            self.tasks = [task for task in self.tasks if task.get("id") != task_id]
            if len(self.tasks) == before:
                raise KeyError(f"Task not found: {task_id}")

    def pause_task(self, task_id):
        now = _now()
        with self.state_lock:
            task = self.find_task(task_id)
            if not task["is_paused"]:
                task["is_paused"] = True
                if task["type"] == "timer":
                    task["remaining_seconds"] = max(0.0, task["target_time"] - now)

    def resume_task(self, task_id):
        now = _now()
        with self.state_lock:
            task = self.find_task(task_id)
            if task["is_paused"]:
                task["is_paused"] = False
                if task["type"] == "timer":
                    task["target_time"] = now + max(0.0, task.get("remaining_seconds", 0.0))
                else:
                    task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"], now)

    def reset_task(self, task_id):
        now = _now()
        with self.state_lock:
            task = self.find_task(task_id)
            if task["type"] == "timer":
                task["remaining_seconds"] = task["duration_minutes"] * 60.0
                if not task["is_paused"]:
                    task["target_time"] = now + task["remaining_seconds"]
            else:
                task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"], now)

    def pause_all(self):
        now = _now()
        with self.state_lock:
            for task in self.tasks:
                if not task["is_paused"]:
                    task["is_paused"] = True
                    if task["type"] == "timer":
                        task["remaining_seconds"] = max(0.0, task["target_time"] - now)

    def resume_all(self):
        now = _now()
        with self.state_lock:
            for task in self.tasks:
                if task["is_paused"]:
                    task["is_paused"] = False
                    if task["type"] == "timer":
                        task["target_time"] = now + max(0.0, task.get("remaining_seconds", 0.0))
                    else:
                        task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"], now)

    def reorder_tasks(self, ids):
        if not isinstance(ids, list):
            raise ValueError("reorderTasks payload.ids must be a list")
        index_by_id = {str(task_id): idx for idx, task_id in enumerate(ids)}
        with self.state_lock:
            for task in self.tasks:
                if task["id"] in index_by_id:
                    task["order"] = float(index_by_id[task["id"]])

    def set_language(self, language):
        if language not in ("zh", "en"):
            raise ValueError("Language must be zh or en")
        if language == self.current_lang:
            return

        old_lang = self.current_lang
        old_default = DEFAULT_GROUP[old_lang]
        new_default = DEFAULT_GROUP[language]
        with self.state_lock:
            self.current_lang = language
            for task in self.tasks:
                if task.get("group") == old_default:
                    task["group"] = new_default

    def check_due_tasks(self, force_save=False):
        now = _now()
        triggered = []
        with self.state_lock:
            for task in self.tasks:
                if task.get("is_paused") or now < _as_float(task.get("target_time"), 0.0):
                    continue
                triggered.append(dict(task))
                if task["type"] == "timer":
                    interval = max(0.1, task["duration_minutes"] * 60.0)
                    if task.get("is_auto_loop", True):
                        target_time = _as_float(task.get("target_time"), now)
                        while target_time <= now:
                            target_time += interval
                        task["target_time"] = target_time
                        task["remaining_seconds"] = interval
                    else:
                        task["is_paused"] = True
                        task["remaining_seconds"] = 0.0
                else:
                    task["target_time"] = calculate_next_alarm(task["alarm_time"], task["repeat_days"], now)

        if triggered:
            self.save_config()
            self.trigger_notification(triggered)
            self.emit({"event": "taskTriggered", "tasks": triggered})
            self.emit_state()
        elif force_save:
            self.save_config()

    def trigger_notification(self, tasks):
        if not tasks or self.notify_disabled:
            return

        self._play_sound(tasks[0].get("sound_path", DEFAULT_SOUND))
        if os.name != "nt":
            return

        try:
            import winrt.windows.data.xml.dom as win_xml
            import winrt.windows.ui.notifications as win_notify

            if len(tasks) == 1:
                title = "NativeLoopTimer"
                message = tasks[0].get("name", DEFAULT_MESSAGE[self.current_lang])
            else:
                title = f"NativeLoopTimer - {len(tasks)} reminders"
                message = "\n".join(f"- {task.get('name', '')}" for task in tasks)

            xml = f"""
            <toast duration="short">
              <visual>
                <binding template="ToastGeneric">
                  <text>{html.escape(title)}</text>
                  <text>{html.escape(message)}</text>
                </binding>
              </visual>
              <audio silent="true"/>
            </toast>
            """
            doc = win_xml.XmlDocument()
            doc.load_xml(xml)
            notifier = win_notify.ToastNotificationManager.create_toast_notifier_with_id(APP_ID)
            notifier.show(win_notify.ToastNotification(doc))
        except Exception:
            pass

    def _play_sound(self, sound_path):
        if self.notify_disabled or os.name != "nt":
            return
        try:
            import winsound

            if sound_path and os.path.exists(sound_path):
                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass


def main():
    configure_stdio()
    backend = NativeLoopBackend()
    backend.run()


if __name__ == "__main__":
    main()
