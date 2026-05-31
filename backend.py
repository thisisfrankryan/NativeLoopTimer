import sys
import json
import time
import threading
import ctypes

class DaemonTimer:
    def __init__(self):
        self.lock = threading.Lock()
        self.duration = 0
        self.remaining = 0
        self.is_paused = False
        self.is_running = False
        self.start_time = 0
        self.pause_time = 0
        self.parent_dead = False

    def start(self, duration):
        with self.lock:
            self.duration = duration
            self.remaining = duration
            self.start_time = time.time()
            self.is_paused = False
            self.is_running = True
            self.pause_time = 0

    def pause(self):
        with self.lock:
            if self.is_running and not self.is_paused:
                self.is_paused = True
                self.pause_time = time.time()

    def resume(self):
        with self.lock:
            if self.is_running and self.is_paused:
                # Adjust start_time to account for paused duration
                paused_duration = time.time() - self.pause_time
                self.start_time += paused_duration
                self.is_paused = False

    def stop(self):
        with self.lock:
            self.is_running = False
            self.remaining = 0

    def get_status(self):
        with self.lock:
            if not self.is_running:
                return None
            
            # Recalculate remaining time using precise epoch differential
            if not self.is_paused:
                elapsed = time.time() - self.start_time
                self.remaining = max(0, self.duration - int(elapsed))
            
            return {
                "status": "tick",
                "remaining": self.remaining,
                "is_paused": self.is_paused
            }

    def trigger_reminder(self):
        # 1. Lock the Windows Workstation
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception as e:
            sys.stderr.write(f"Lock screen failed: {e}\n")
            sys.stderr.flush()

        # 2. Display a system-modal blocking message box
        try:
            # 0x40000 = MB_SYSTEMMODAL (Stays on top of all screens)
            # 0x40 = MB_ICONINFORMATION
            # 0x0 = MB_OK
            ctypes.windll.user32.MessageBoxW(
                0, 
                "时间到了！请立即起来活动身体，远眺休息，喝杯水放松一下吧！", 
                "NativeLoopTimer 护眼提醒", 
                0x40000 | 0x40 | 0x0
            )
        except Exception as e:
            sys.stderr.write(f"Message box failed: {e}\n")
            sys.stderr.flush()


def listen_stdin(timer):
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                # Empty string indicates standard input pipe is broken (Parent process exited)
                timer.parent_dead = True
                with timer.lock:
                    if not timer.is_running:
                        # If idle, exit immediately to prevent zombie process
                        sys.exit(0)
                break
                
            data = json.loads(line.strip())
            action = data.get("action")
            
            if action == "start":
                duration = int(data.get("duration", 1200))
                timer.start(duration)
            elif action == "pause":
                timer.pause()
            elif action == "resume":
                timer.resume()
            elif action == "stop":
                timer.stop()
                
        except (json.JSONDecodeError, ValueError):
            # Gracefully ignore invalid commands
            pass
        except Exception:
            break


def main():
    timer = DaemonTimer()
    
    # Spawn daemon thread to handle stdin without blocking our high-precision timer
    stdin_thread = threading.Thread(target=listen_stdin, args=(timer,), daemon=True)
    stdin_thread.start()

    while True:
        time.sleep(0.1) # Small cycle sleep to save CPU usage
        
        status = timer.get_status()
        
        if status is not None:
            # Check for expiration
            if status["remaining"] <= 0:
                # Expiration event triggered!
                try:
                    sys.stdout.write(json.dumps({"status": "expired"}) + "\n")
                    sys.stdout.flush()
                except Exception:
                    pass
                
                # Active locking / reminding
                timer.trigger_reminder()
                
                # Complete the timer
                timer.stop()
                sys.exit(0)
                
            # Periodic single-line JSON Tick Output
            try:
                sys.stdout.write(json.dumps(status) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                # Parent process pipe is severed! Set parent_dead flag
                timer.parent_dead = True
                
        # If parent process has exited
        if timer.parent_dead:
            with timer.lock:
                if not timer.is_running:
                    # If idle, terminate immediately
                    sys.exit(0)


if __name__ == "__main__":
    main()
