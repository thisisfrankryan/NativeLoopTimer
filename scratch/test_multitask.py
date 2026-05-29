import sys
import os
import time
import json
import uuid

# Add workspace to system path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import TimerApp, calculate_next_alarm

# Isolated test config directory to protect production settings
app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
test_config_dir = os.path.join(app_dir, "test_config")
os.makedirs(test_config_dir, exist_ok=True)

def test_alarm_scheduler():
    print("\n=== Testing Alarm Scheduler Logic ===")
    
    # Test 1: Single one-off alarm scheduled for a future hour today
    import datetime
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    future_time = now + datetime.timedelta(minutes=5)
    future_str = future_time.strftime("%H:%M")
    
    epoch = calculate_next_alarm(future_str, [])
    diff = epoch - now.timestamp()
    print(f"One-off Alarm today in 5 mins: {future_str} -> triggers in {diff:.1f}s")
    assert 295 <= diff <= 305, f"Should trigger in roughly 300 seconds, got {diff:.1f}"

    # Test 2: Single one-off alarm in the past today -> should schedule for tomorrow
    past_time = now - datetime.timedelta(minutes=5)
    past_str = past_time.strftime("%H:%M")
    epoch_tomorrow = calculate_next_alarm(past_str, [])
    diff_tomorrow = epoch_tomorrow - now.timestamp()
    print(f"One-off Alarm past today: {past_str} -> triggers in tomorrow ({diff_tomorrow/3600:.1f} hours)")
    assert 23.8 * 3600 <= diff_tomorrow <= 24.2 * 3600, "Should schedule for tomorrow"

    # Test 3: Weekly recurring alarm (specific days)
    # Mon=1, Tue=2, Wed=3, Thu=4, Fri=5, Sat=6, Sun=7
    weekday_today = now.isoweekday()
    epoch_recur = calculate_next_alarm(future_str, [weekday_today])
    diff_recur = epoch_recur - now.timestamp()
    print(f"Recurring Alarm today in 5 mins: {future_str} -> triggers in {diff_recur:.1f}s")
    assert 295 <= diff_recur <= 305, "Should trigger in roughly 300 seconds"
    
    print("✅ Alarm scheduler unit tests PASSED!")

def test_concurrency_and_persistence():
    print("\n=== Testing Concurrency & Persistence ===")
    
    # Clear test config directory first to start fresh
    config_path = os.path.join(test_config_dir, "config.json")
    if os.path.exists(config_path):
        os.remove(config_path)
        
    app = TimerApp(config_dir=test_config_dir)
    
    # Add a relative Timer (0.02 mins = 1.2s)
    # Simulate adding via GUI
    task1 = {
        "id": str(uuid.uuid4()),
        "type": "timer",
        "name": "多任务测试-定时器",
        "duration_minutes": 0.02,
        "is_auto_loop": False,
        "is_paused": False,
        "created_at": time.time(),
        "target_time": time.time() + 1.2,
        "remaining_seconds": 1.2
    }
    
    # Add an absolute Alarm scheduled in 1.5 seconds
    import datetime
    alarm_time = datetime.datetime.now() + datetime.timedelta(seconds=1.5)
    alarm_str = alarm_time.strftime("%H:%M")
    task2 = {
        "id": str(uuid.uuid4()),
        "type": "alarm",
        "name": "多任务测试-闹钟",
        "alarm_time": alarm_str,
        "repeat_days": [],
        "is_paused": False,
        "target_time": time.time() + 1.5
    }
    
    with app.lock:
        app.tasks = [task1, task2]
        
    # Save and verify config.json exists and contains correct items
    app.save_config()
    assert os.path.exists(config_path), "config.json should be written"
    
    with open(config_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
        saved_tasks = saved_data["tasks"]
        print(f"Persisted task count: {len(saved_tasks)}")
        assert len(saved_tasks) == 2
        assert saved_tasks[0]["name"] == "多任务测试-定时器"
        assert saved_tasks[1]["name"] == "多任务测试-闹钟"
        
    print("Waiting 2.5 seconds for both tasks to expire and trigger...")
    time.sleep(2.5)
    
    print("Checking final states...")
    with app.lock:
        print(f"Task 1 (Timer) paused state: {app.tasks[0]['is_paused']}")
        assert app.tasks[0]["is_paused"] == True, "Timer should pause after expiring since loop=False"
        
    print("Exiting app...")
    app.exit_app()
    print("✅ Concurrency & Persistence tests PASSED!")

def test_merged_sleep_compensation():
    print("\n=== Testing Merged Wakeup Compensation ===")
    app = TimerApp(config_dir=test_config_dir)
    
    # Simulate two expired tasks due to sleep
    task1 = {
        "id": str(uuid.uuid4()),
        "type": "timer",
        "name": "被错过的番茄钟提醒",
        "duration_minutes": 20.0,
        "is_auto_loop": True,
        "is_paused": False,
        "created_at": time.time() - 3600,
        "target_time": time.time() - 1800, # expired 30 mins ago
        "remaining_seconds": 1200.0
    }
    
    task2 = {
        "id": str(uuid.uuid4()),
        "type": "alarm",
        "name": "被错过的部门早会闹钟",
        "alarm_time": "09:00",
        "repeat_days": [],
        "is_paused": False,
        "target_time": time.time() - 600 # expired 10 mins ago
    }
    
    with app.lock:
        app.tasks = [task1, task2]
        
    print("Emulating system wakeup. Calling check_and_compensate_missed_tasks...")
    # This should merge both alerts and deliver exactly one notification
    app.check_and_compensate_missed_tasks(time.time())
    
    with app.lock:
        # Check that target times are recalculated and advanced in the future
        print(f"Task 1 rescheduled target: in {app.tasks[0]['target_time'] - time.time():.1f}s")
        print(f"Task 2 rescheduled target: in {app.tasks[1]['target_time'] - time.time():.1f}s")
        assert app.tasks[0]["target_time"] > time.time()
        assert app.tasks[1]["target_time"] > time.time()
        
    app.exit_app()
    print("✅ Merged sleep compensation tests PASSED!")

def test_intelligent_time_parsing():
    print("\n=== Testing Intelligent Time Parsing ===")
    app = TimerApp(config_dir=test_config_dir)
    
    assert app.validate_alarm_time("830") == "08:30", f"Expected 08:30, got {app.validate_alarm_time('830')}"
    assert app.validate_alarm_time("8 30") == "08:30"
    assert app.validate_alarm_time("0830") == "08:30"
    assert app.validate_alarm_time("8") == "08:00"
    assert app.validate_alarm_time("14:30") == "14:30"
    assert app.validate_alarm_time("1430") == "14:30"
    assert app.validate_alarm_time("abc") is None
    assert app.validate_alarm_time("2560") is None
    
    assert app.validate_alarm_time("8", "30", "AM") == "08:30"
    assert app.validate_alarm_time("8", "30", "PM") == "20:30"
    assert app.validate_alarm_time("12", "00", "AM") == "00:00"
    assert app.validate_alarm_time("12", "00", "PM") == "12:00"
    assert app.validate_alarm_time("13", "00", "AM") is None
    
    app.exit_app()
    print("✅ Intelligent time parsing unit tests PASSED!")

def test_manual_reset():
    print("\n=== Testing Manual Reset ===")
    app = TimerApp(config_dir=test_config_dir)
    
    # 1. Timer Reset while active (not paused)
    task1 = {
        "id": "test-timer-reset",
        "type": "timer",
        "name": "Reset Test Timer",
        "duration_minutes": 10.0,
        "is_auto_loop": False,
        "is_paused": False,
        "created_at": time.time(),
        "target_time": time.time() + 300.0, # 5 mins left
        "remaining_seconds": 300.0
    }
    
    # 2. Timer Reset while paused
    task2 = {
        "id": "test-timer-reset-paused",
        "type": "timer",
        "name": "Reset Test Timer Paused",
        "duration_minutes": 15.0,
        "is_auto_loop": False,
        "is_paused": True,
        "created_at": time.time(),
        "target_time": time.time() + 100.0,
        "remaining_seconds": 200.0 # 200s left
    }
    
    # 3. Alarm Reset
    task3 = {
        "id": "test-alarm-reset",
        "type": "alarm",
        "name": "Reset Test Alarm",
        "alarm_time": "08:30",
        "repeat_days": [],
        "is_paused": False,
        "target_time": time.time() - 3600.0 # expired 1 hr ago
    }
    
    with app.lock:
        app.tasks = [task1, task2, task3]
        
    # Reset active timer
    app.reset_task("test-timer-reset")
    with app.lock:
        t1 = app.tasks[0]
        # Active timer remaining seconds should reset, and target time should advance to now + 600s
        diff = t1["target_time"] - time.time()
        print(f"Active Timer Reset: target in {diff:.1f}s (expected ~600s)")
        assert 590 <= diff <= 610, "Should reset to 10 mins (600s)"
        assert t1["is_paused"] == False

    # Reset paused timer
    app.reset_task("test-timer-reset-paused")
    with app.lock:
        t2 = app.tasks[1]
        # Paused timer remaining seconds should reset to 15 * 60 = 900s, state remains paused
        print(f"Paused Timer Reset: remaining seconds = {t2['remaining_seconds']}s (expected 900s)")
        assert t2["remaining_seconds"] == 900.0
        assert t2["is_paused"] == True
        
    # Reset expired alarm
    app.reset_task("test-alarm-reset")
    with app.lock:
        t3 = app.tasks[2]
        # Recalculated target time should be in the future (greater than current time)
        print(f"Alarm Reset: target time recalculation -> future: {t3['target_time'] > time.time()}")
        assert t3["target_time"] > time.time()

    app.exit_app()
    print("✅ Manual Reset unit tests PASSED!")

if __name__ == "__main__":
    import shutil
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(app_dir, "config.json")
    backup_path = os.path.join(app_dir, "config.json.bak")
    
    # Safely back up the production config if it exists
    has_backup = False
    if os.path.exists(config_path):
        try:
            shutil.copy2(config_path, backup_path)
            has_backup = True
        except Exception as e:
            print(f"Warning: Could not create config backup: {e}")
            
    try:
        test_intelligent_time_parsing()
        test_alarm_scheduler()
        test_concurrency_and_persistence()
        test_merged_sleep_compensation()
        test_manual_reset()
        print("\n🏆 All tests passed successfully!")
    finally:
        # Restore the backup config if it was successfully backed up
        if has_backup:
            try:
                shutil.copy2(backup_path, config_path)
                os.remove(backup_path)
                print("\n[Test Suite] Restored original config.json successfully.")
            except Exception as e:
                print(f"Error: Could not restore config backup: {e}")
        else:
            # If there was no original config, clean up the test-generated config file
            if os.path.exists(config_path):
                try:
                    os.remove(config_path)
                except Exception:
                    pass
        # Clean up the isolated test config folder
        if os.path.exists(test_config_dir):
            try:
                shutil.rmtree(test_config_dir)
            except Exception:
                pass
