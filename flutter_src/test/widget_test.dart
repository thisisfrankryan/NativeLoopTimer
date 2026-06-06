import 'package:flutter_test/flutter_test.dart';
import 'package:native_loop_timer/main.dart';

void main() {
  test('TimerTask computes active and paused timer progress', () {
    final now = DateTime.now();
    final active = TimerTask.fromJson({
      'id': 'timer-1',
      'type': 'timer',
      'name': 'Focus',
      'group': 'Work',
      'duration_minutes': 10,
      'is_paused': false,
      'target_time': now.add(const Duration(minutes: 5)).millisecondsSinceEpoch / 1000,
      'remaining_seconds': 600,
      'created_at': 1,
      'order': 1,
    });

    expect(active.remainingAt(now), closeTo(300, 1));
    expect(active.progressAt(now), closeTo(0.5, 0.02));

    final paused = active.copyWith(isPaused: true, remainingSeconds: 120);
    expect(paused.remainingAt(now), 120);
    expect(paused.progressAt(now), closeTo(0.2, 0.001));
  });

  test('TimerTask normalizes alarm repeat days', () {
    final alarm = TimerTask.fromJson({
      'id': 'alarm-1',
      'type': 'alarm',
      'name': 'Standup',
      'group': 'Work',
      'alarm_time': '08:30',
      'repeat_days': [5, '1', 9, 1],
      'target_time': 100,
      'created_at': 1,
      'order': 1,
    });

    expect(alarm.type, TaskType.alarm);
    expect(alarm.repeatDays, [1, 5]);
    expect(alarm.progressAt(DateTime.now()), 1.0);
  });
}
