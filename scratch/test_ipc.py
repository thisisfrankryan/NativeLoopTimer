import subprocess
import json
import time
import sys
import os

def read_until_state(process, key, expected_value, timeout=2.0):
    start = time.time()
    while time.time() - start < timeout:
        line = process.stdout.readline()
        if not line:
            break
        try:
            status = json.loads(line.strip())
            if status.get(key) == expected_value:
                return status
        except json.JSONDecodeError:
            pass
    raise TimeoutError(f"Timed out waiting for state {key} == {expected_value}")

def run_ipc_test():
    print("=== Starting IPC Pipe Verification Test ===")
    
    # Path to backend.py
    backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend.py")
    
    # Spawn Python subprocess with pipe redirections
    process = subprocess.Popen(
        [sys.executable, backend_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    try:
        # 1. Send start timer command (duration 5 seconds)
        print("Sending: start timer for 5 seconds...")
        cmd_start = {"action": "start", "duration": 5}
        process.stdin.write(json.dumps(cmd_start) + "\n")
        process.stdin.flush()
        
        # Verify timer is running
        status = read_until_state(process, "is_paused", False)
        print(f"Verified Running tick: {status}")
        assert status["status"] == "tick"
        assert status["remaining"] <= 5
        
        # 2. Send pause command
        print("Sending: pause...")
        cmd_pause = {"action": "pause"}
        process.stdin.write(json.dumps(cmd_pause) + "\n")
        process.stdin.flush()
        
        # Verify timer pauses
        status = read_until_state(process, "is_paused", True)
        print(f"Verified Paused tick: {status}")
        paused_remaining = status["remaining"]
        
        # Verify that remaining time stays frozen
        time.sleep(0.8)
        line = process.stdout.readline()
        status = json.loads(line.strip())
        print(f"Verified Frozen check tick: {status}")
        assert status["remaining"] == paused_remaining
        
        # 3. Send resume command
        print("Sending: resume...")
        cmd_resume = {"action": "resume"}
        process.stdin.write(json.dumps(cmd_resume) + "\n")
        process.stdin.flush()
        
        # Verify timer resumes
        status = read_until_state(process, "is_paused", False)
        print(f"Verified Resumed tick: {status}")
        
        # 4. Send stop command
        print("Sending: stop...")
        cmd_stop = {"action": "stop"}
        process.stdin.write(json.dumps(cmd_stop) + "\n")
        process.stdin.flush()
        
        print("Closing stdin pipe (Simulating parent process exit)...")
        process.stdin.close()
        
        # Subprocess should immediately detect parent process death while stopped and exit gracefully
        time.sleep(0.5)
        exit_code = process.poll()
        print(f"Subprocess exit code: {exit_code}")
        assert exit_code == 0, f"Expected clean exit (0), got {exit_code}"
        
        print("[PASS] IPC Pipe Verification Test PASSED!")
        
    except Exception as e:
        print(f"[FAIL] Test Failed: {e}")
        process.kill()
        sys.exit(1)

if __name__ == "__main__":
    run_ipc_test()
