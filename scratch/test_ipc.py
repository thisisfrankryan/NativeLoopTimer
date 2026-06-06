import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND = ROOT / "backend.py"


def _backend_command():
    override = os.environ.get("NATIVE_LOOP_TIMER_TEST_BACKEND")
    if override:
        return [override]
    return [sys.executable, str(DEFAULT_BACKEND)]


def _read_packet(process, timeout=5.0, request_id=None, event=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = process.stdout.readline()
        if not line:
            continue
        packet = json.loads(line)
        if request_id is not None and packet.get("requestId") != request_id:
            continue
        if event is not None and packet.get("event") != event:
            continue
        return packet
    raise TimeoutError(f"Timed out waiting for request_id={request_id!r}, event={event!r}")


def _send(process, command, payload=None, request_id=None):
    request_id = request_id or command
    packet = {"command": command, "requestId": request_id}
    if payload is not None:
        packet["payload"] = payload
    process.stdin.write(json.dumps(packet, ensure_ascii=False) + "\n")
    process.stdin.flush()
    return request_id


def _state_for(process, command, payload=None, request_id=None):
    rid = _send(process, command, payload, request_id)
    return _read_packet(process, request_id=rid, event="stateSnapshot")


def _task(snapshot, task_id):
    for task in snapshot["tasks"]:
        if task["id"] == task_id:
            return task
    raise AssertionError(f"Task {task_id} not present in snapshot")


def run_ipc_test():
    print("=== NativeLoopTimer backend IPC verification ===")
    with tempfile.TemporaryDirectory(prefix="native_loop_timer_ipc_") as config_dir:
        env = os.environ.copy()
        env["NATIVE_LOOP_TIMER_CONFIG_DIR"] = config_dir
        env["NATIVE_LOOP_TIMER_DISABLE_NOTIFY"] = "1"
        env["NATIVE_LOOP_TIMER_DISABLE_POWER_MONITOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        process = subprocess.Popen(
            _backend_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            bufsize=1,
        )

        try:
            initial = _read_packet(process, event="stateSnapshot")
            assert initial["tasks"] == []
            assert initial["language"] == "zh"

            created = _state_for(
                process,
                "createTask",
                {
                    "type": "timer",
                    "name": "IPC Timer",
                    "duration_minutes": 0.05,
                    "is_auto_loop": False,
                    "group": "Focus",
                },
                "create-timer",
            )
            assert len(created["tasks"]) == 1
            timer_id = created["tasks"][0]["id"]
            assert created["tasks"][0]["type"] == "timer"
            assert created["tasks"][0]["is_paused"] is False

            paused = _state_for(process, "pauseTask", {"id": timer_id}, "pause-timer")
            assert _task(paused, timer_id)["is_paused"] is True
            assert _task(paused, timer_id)["remaining_seconds"] > 0

            resumed = _state_for(process, "resumeTask", {"id": timer_id}, "resume-timer")
            assert _task(resumed, timer_id)["is_paused"] is False

            reset = _state_for(process, "resetTask", {"id": timer_id}, "reset-timer")
            assert 2.5 <= _task(reset, timer_id)["remaining_seconds"] <= 3.1

            alarm_state = _state_for(
                process,
                "createTask",
                {
                    "type": "alarm",
                    "name": "IPC Alarm",
                    "alarm_time": "23:59",
                    "repeat_days": [1, 2, 3],
                    "group": "Focus",
                },
                "create-alarm",
            )
            assert len(alarm_state["tasks"]) == 2
            alarm_id = next(task["id"] for task in alarm_state["tasks"] if task["type"] == "alarm")

            reordered = _state_for(process, "reorderTasks", {"ids": [alarm_id, timer_id]}, "reorder")
            assert _task(reordered, alarm_id)["order"] == 0.0
            assert _task(reordered, timer_id)["order"] == 1.0

            english = _state_for(process, "setLanguage", {"language": "en"}, "language")
            assert english["language"] == "en"

            deleted = _state_for(process, "deleteTask", {"id": timer_id}, "delete-timer")
            assert len(deleted["tasks"]) == 1
            assert deleted["tasks"][0]["id"] == alarm_id

            _send(process, "shutdown", request_id="shutdown")
            shutdown = _read_packet(process, request_id="shutdown", event="shutdown")
            assert shutdown["event"] == "shutdown"
            assert process.wait(timeout=5) == 0

            config_path = Path(config_dir) / "config.json"
            assert config_path.exists()
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            assert saved["language"] == "en"
            assert len(saved["tasks"]) == 1
            print("[PASS] Backend IPC verification passed")
        except Exception:
            process.kill()
            stderr = process.stderr.read() if process.stderr else ""
            if stderr:
                print(stderr)
            raise


if __name__ == "__main__":
    run_ipc_test()
