import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:system_tray/system_tray.dart';
import 'package:window_manager/window_manager.dart';

import 'assets_manager.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  const windowOptions = WindowOptions(
    size: Size(1180, 760),
    minimumSize: Size(940, 620),
    center: true,
    title: 'NativeLoopTimer',
    titleBarStyle: TitleBarStyle.normal,
  );

  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
    await windowManager.setPreventClose(true);
  });

  runApp(const NativeLoopTimerApp());
}

class NativeLoopTimerApp extends StatelessWidget {
  const NativeLoopTimerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'NativeLoopTimer',
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF10B981),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF0B1020),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF101827),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xFF334155)),
          ),
        ),
      ),
      home: const DashboardPage(),
    );
  }
}

enum TaskType { timer, alarm }

TaskType _taskTypeFromString(String value) {
  return value == 'alarm' ? TaskType.alarm : TaskType.timer;
}

String _taskTypeToString(TaskType type) {
  return type == TaskType.alarm ? 'alarm' : 'timer';
}

double _doubleFromJson(Object? value, [double fallback = 0.0]) {
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '') ?? fallback;
}

bool _boolFromJson(Object? value, [bool fallback = false]) {
  if (value is bool) return value;
  if (value is String) {
    return const {'1', 'true', 'yes', 'on'}.contains(value.toLowerCase());
  }
  return value == null ? fallback : value != 0;
}

List<int> _repeatDaysFromJson(Object? value) {
  if (value is! Iterable) return const [];
  final days = <int>{};
  for (final item in value) {
    final day = int.tryParse(item.toString());
    if (day != null && day >= 1 && day <= 7) {
      days.add(day);
    }
  }
  return days.toList()..sort();
}

class TimerTask {
  final String id;
  final TaskType type;
  final String name;
  final String group;
  final String soundPath;
  final bool isPaused;
  final double createdAt;
  final double order;
  final double durationMinutes;
  final bool isAutoLoop;
  final double targetTime;
  final double remainingSeconds;
  final String alarmTime;
  final List<int> repeatDays;

  const TimerTask({
    required this.id,
    required this.type,
    required this.name,
    required this.group,
    required this.soundPath,
    required this.isPaused,
    required this.createdAt,
    required this.order,
    required this.durationMinutes,
    required this.isAutoLoop,
    required this.targetTime,
    required this.remainingSeconds,
    required this.alarmTime,
    required this.repeatDays,
  });

  factory TimerTask.fromJson(Map<String, dynamic> json) {
    final type = _taskTypeFromString(json['type']?.toString() ?? 'timer');
    return TimerTask(
      id: json['id']?.toString() ?? '',
      type: type,
      name: json['name']?.toString() ?? '',
      group: json['group']?.toString() ?? 'Default',
      soundPath: json['sound_path']?.toString() ?? '',
      isPaused: _boolFromJson(json['is_paused']),
      createdAt: _doubleFromJson(json['created_at']),
      order: _doubleFromJson(json['order'], _doubleFromJson(json['created_at'])),
      durationMinutes: _doubleFromJson(json['duration_minutes'], 20.0),
      isAutoLoop: _boolFromJson(json['is_auto_loop'], true),
      targetTime: _doubleFromJson(json['target_time']),
      remainingSeconds: _doubleFromJson(json['remaining_seconds']),
      alarmTime: json['alarm_time']?.toString() ?? '08:30',
      repeatDays: _repeatDaysFromJson(json['repeat_days']),
    );
  }

  Map<String, dynamic> toPayload() {
    return {
      'id': id,
      'type': _taskTypeToString(type),
      'name': name,
      'group': group,
      'sound_path': soundPath,
      'is_paused': isPaused,
      'created_at': createdAt,
      'order': order,
      'duration_minutes': durationMinutes,
      'is_auto_loop': isAutoLoop,
      'target_time': targetTime,
      'remaining_seconds': remainingSeconds,
      'alarm_time': alarmTime,
      'repeat_days': repeatDays,
    };
  }

  TimerTask copyWith({
    String? name,
    String? group,
    String? soundPath,
    bool? isPaused,
    double? order,
    double? durationMinutes,
    bool? isAutoLoop,
    double? targetTime,
    double? remainingSeconds,
    String? alarmTime,
    List<int>? repeatDays,
  }) {
    return TimerTask(
      id: id,
      type: type,
      name: name ?? this.name,
      group: group ?? this.group,
      soundPath: soundPath ?? this.soundPath,
      isPaused: isPaused ?? this.isPaused,
      createdAt: createdAt,
      order: order ?? this.order,
      durationMinutes: durationMinutes ?? this.durationMinutes,
      isAutoLoop: isAutoLoop ?? this.isAutoLoop,
      targetTime: targetTime ?? this.targetTime,
      remainingSeconds: remainingSeconds ?? this.remainingSeconds,
      alarmTime: alarmTime ?? this.alarmTime,
      repeatDays: repeatDays ?? this.repeatDays,
    );
  }

  double remainingAt(DateTime now) {
    if (type == TaskType.timer) {
      if (isPaused) {
        return math.max(0.0, remainingSeconds);
      }
      return math.max(0.0, targetTime - now.millisecondsSinceEpoch / 1000.0);
    }
    return math.max(0.0, targetTime - now.millisecondsSinceEpoch / 1000.0);
  }

  double progressAt(DateTime now) {
    if (type == TaskType.alarm) return 1.0;
    final total = math.max(0.1, durationMinutes * 60.0);
    return (remainingAt(now) / total).clamp(0.0, 1.0);
  }
}

class AppState {
  final String language;
  final List<TimerTask> tasks;
  final Map<String, Map<String, String>> soundOptions;
  final String configPath;
  final String? lastError;

  const AppState({
    required this.language,
    required this.tasks,
    required this.soundOptions,
    required this.configPath,
    this.lastError,
  });

  factory AppState.initial() {
    return const AppState(
      language: 'zh',
      tasks: [],
      soundOptions: {
        'zh': {'系统默认': 'C:/Windows/Media/Windows Default.wav'},
        'en': {'System Default': 'C:/Windows/Media/Windows Default.wav'},
      },
      configPath: '',
    );
  }

  AppState copyWith({
    String? language,
    List<TimerTask>? tasks,
    Map<String, Map<String, String>>? soundOptions,
    String? configPath,
    String? lastError,
  }) {
    return AppState(
      language: language ?? this.language,
      tasks: tasks ?? this.tasks,
      soundOptions: soundOptions ?? this.soundOptions,
      configPath: configPath ?? this.configPath,
      lastError: lastError,
    );
  }
}

class BackendController extends ChangeNotifier {
  Process? _process;
  AppState _state = AppState.initial();
  int _requestCounter = 0;
  bool _started = false;

  AppState get state => _state;
  bool get isStarted => _started;

  Future<void> start() async {
    if (_started) return;
    _started = true;
    try {
      final launch = await AssetsManager.resolveBackendLaunch();
      _process = await Process.start(
        launch.executable,
        launch.arguments,
        runInShell: Platform.isWindows,
        environment: {
          ...Platform.environment,
          'PYTHONIOENCODING': 'utf-8',
        },
      );

      _process!.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(_handleBackendLine, onError: (Object error) {
        _setError(error.toString());
      });

      _process!.stderr.transform(utf8.decoder).listen((chunk) {
        final text = chunk.trim();
        if (text.isNotEmpty) _setError(text);
      });

      _process!.exitCode.then((code) {
        if (code != 0) {
          _setError('Backend exited with code $code');
        }
      });

      send('loadState');
    } catch (error) {
      _setError('Unable to start backend: $error');
    }
  }

  void _handleBackendLine(String line) {
    if (line.trim().isEmpty) return;
    try {
      final packet = jsonDecode(line) as Map<String, dynamic>;
      final event = packet['event']?.toString();
      if (event == 'stateSnapshot') {
        final tasks = <TimerTask>[];
        final rawTasks = packet['tasks'];
        if (rawTasks is List) {
          for (final rawTask in rawTasks) {
            if (rawTask is Map) {
              tasks.add(TimerTask.fromJson(Map<String, dynamic>.from(rawTask)));
            }
          }
        }

        _state = _state.copyWith(
          language: packet['language']?.toString() == 'en' ? 'en' : 'zh',
          tasks: tasks,
          soundOptions: _parseSoundOptions(packet['soundOptions']),
          configPath: packet['configPath']?.toString() ?? _state.configPath,
        );
        notifyListeners();
      } else if (event == 'error') {
        _setError(packet['message']?.toString() ?? 'Backend error');
      } else if (event == 'taskUpdated' && packet['task'] is Map) {
        final task = TimerTask.fromJson(Map<String, dynamic>.from(packet['task'] as Map));
        _replaceTask(task);
      }
    } catch (error) {
      _setError('Bad backend packet: $error');
    }
  }

  Map<String, Map<String, String>> _parseSoundOptions(Object? value) {
    final fallback = _state.soundOptions;
    if (value is! Map) return fallback;
    final result = <String, Map<String, String>>{};
    for (final lang in const ['zh', 'en']) {
      final langMap = value[lang];
      if (langMap is Map) {
        result[lang] = {
          for (final entry in langMap.entries) entry.key.toString(): entry.value.toString(),
        };
      }
    }
    return result.isEmpty ? fallback : result;
  }

  void _setError(String error) {
    _state = _state.copyWith(lastError: error);
    notifyListeners();
  }

  void _replaceTask(TimerTask task) {
    final tasks = [..._state.tasks];
    final index = tasks.indexWhere((item) => item.id == task.id);
    if (index >= 0) {
      tasks[index] = task;
    } else {
      tasks.add(task);
    }
    _state = _state.copyWith(tasks: tasks, lastError: null);
    notifyListeners();
  }

  void send(String command, [Map<String, dynamic>? payload]) {
    final process = _process;
    if (process == null) return;
    final packet = {
      'command': command,
      'requestId': (++_requestCounter).toString(),
      if (payload != null) 'payload': payload,
    };
    process.stdin.writeln(jsonEncode(packet));
  }

  void createTask(Map<String, dynamic> payload) {
    send('createTask', payload);
  }

  void updateTask(String id, Map<String, dynamic> payload) {
    final merged = {'id': id, ...payload};
    _optimisticUpdate(id, payload);
    send('updateTask', merged);
  }

  void deleteTask(String id) {
    _state = _state.copyWith(tasks: _state.tasks.where((task) => task.id != id).toList());
    notifyListeners();
    send('deleteTask', {'id': id});
  }

  void pauseTask(String id) {
    final now = DateTime.now();
    _mutateTask(id, (task) {
      return task.copyWith(
        isPaused: true,
        remainingSeconds: task.type == TaskType.timer ? task.remainingAt(now) : task.remainingSeconds,
      );
    });
    send('pauseTask', {'id': id});
  }

  void resumeTask(String id) {
    final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
    _mutateTask(id, (task) {
      if (task.type == TaskType.timer) {
        return task.copyWith(isPaused: false, targetTime: now + task.remainingSeconds);
      }
      return task.copyWith(isPaused: false);
    });
    send('resumeTask', {'id': id});
  }

  void resetTask(String id) {
    final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
    _mutateTask(id, (task) {
      if (task.type == TaskType.timer) {
        final remaining = task.durationMinutes * 60.0;
        return task.copyWith(
          remainingSeconds: remaining,
          targetTime: task.isPaused ? task.targetTime : now + remaining,
        );
      }
      return task;
    });
    send('resetTask', {'id': id});
  }

  void pauseAll() {
    final now = DateTime.now();
    _state = _state.copyWith(
      tasks: _state.tasks.map((task) {
        if (task.isPaused) return task;
        return task.copyWith(
          isPaused: true,
          remainingSeconds: task.type == TaskType.timer ? task.remainingAt(now) : task.remainingSeconds,
        );
      }).toList(),
    );
    notifyListeners();
    send('pauseAll');
  }

  void resumeAll() {
    final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
    _state = _state.copyWith(
      tasks: _state.tasks.map((task) {
        if (!task.isPaused) return task;
        if (task.type == TaskType.timer) {
          return task.copyWith(isPaused: false, targetTime: now + task.remainingSeconds);
        }
        return task.copyWith(isPaused: false);
      }).toList(),
    );
    notifyListeners();
    send('resumeAll');
  }

  void reorderTasks(List<String> ids) {
    final indexById = <String, int>{};
    for (var i = 0; i < ids.length; i++) {
      indexById[ids[i]] = i;
    }
    _state = _state.copyWith(
      tasks: _state.tasks.map((task) {
        final index = indexById[task.id];
        return index == null ? task : task.copyWith(order: index.toDouble());
      }).toList(),
    );
    notifyListeners();
    send('reorderTasks', {'ids': ids});
  }

  void setLanguage(String language) {
    if (language != 'zh' && language != 'en') return;
    _state = _state.copyWith(language: language);
    notifyListeners();
    send('setLanguage', {'language': language});
  }

  void _optimisticUpdate(String id, Map<String, dynamic> payload) {
    _mutateTask(id, (task) {
      return task.copyWith(
        name: payload['name']?.toString(),
        group: payload['group']?.toString(),
        soundPath: payload['sound_path']?.toString(),
        durationMinutes: payload['duration_minutes'] is num
            ? (payload['duration_minutes'] as num).toDouble()
            : null,
        isAutoLoop: payload['is_auto_loop'] is bool ? payload['is_auto_loop'] as bool : null,
        alarmTime: payload['alarm_time']?.toString(),
        repeatDays: payload['repeat_days'] is List
            ? (payload['repeat_days'] as List).map((item) => int.parse(item.toString())).toList()
            : null,
      );
    });
  }

  void _mutateTask(String id, TimerTask Function(TimerTask task) mutate) {
    var changed = false;
    final tasks = _state.tasks.map((task) {
      if (task.id != id) return task;
      changed = true;
      return mutate(task);
    }).toList();
    if (changed) {
      _state = _state.copyWith(tasks: tasks, lastError: null);
      notifyListeners();
    }
  }

  Future<void> disposeBackend() async {
    final process = _process;
    if (process == null) return;
    try {
      send('shutdown');
      await process.stdin.flush();
      await process.stdin.close();
    } catch (_) {
      process.kill();
    } finally {
      _process = null;
    }
  }
}

class Strings {
  static const values = {
    'zh': {
      'title': '多任务定时中心',
      'subtitle': '计时器、闹钟、分组与托盘常驻',
      'folders': '分组',
      'allTasks': '全部任务',
      'empty': '暂无任务',
      'addTimer': '添加任务',
      'timer': '定时器',
      'alarm': '闹钟',
      'pauseAll': '暂停全部',
      'resumeAll': '恢复全部',
      'language': 'English',
      'compact': '迷你窗',
      'back': '返回',
      'defaultGroup': '默认',
      'name': '提醒内容',
      'group': '分组',
      'duration': '分钟',
      'time': '时间',
      'sound': '提示音',
      'autoLoop': '自动循环',
      'repeat': '重复',
      'oneOff': '单次',
      'save': '保存',
      'cancel': '取消',
      'delete': '删除',
      'edit': '编辑',
      'pause': '暂停',
      'resume': '恢复',
      'reset': '重置',
      'running': '运行中',
      'paused': '已暂停',
      'config': '配置',
      'errorName': '请输入提醒内容',
      'errorDuration': '分钟必须大于 0',
      'errorAlarm': '请输入有效时间',
      'newTask': '新建任务',
      'editTask': '编辑任务',
    },
    'en': {
      'title': 'Multi-Task Timer Center',
      'subtitle': 'Timers, alarms, folders and tray residency',
      'folders': 'Folders',
      'allTasks': 'All Tasks',
      'empty': 'No tasks',
      'addTimer': 'Add Task',
      'timer': 'Timer',
      'alarm': 'Alarm',
      'pauseAll': 'Pause All',
      'resumeAll': 'Resume All',
      'language': '中文',
      'compact': 'Mini',
      'back': 'Back',
      'defaultGroup': 'Default',
      'name': 'Message',
      'group': 'Group',
      'duration': 'Minutes',
      'time': 'Time',
      'sound': 'Sound',
      'autoLoop': 'Auto Loop',
      'repeat': 'Repeat',
      'oneOff': 'One-off',
      'save': 'Save',
      'cancel': 'Cancel',
      'delete': 'Delete',
      'edit': 'Edit',
      'pause': 'Pause',
      'resume': 'Resume',
      'reset': 'Reset',
      'running': 'Running',
      'paused': 'Paused',
      'config': 'Config',
      'errorName': 'Enter a message',
      'errorDuration': 'Minutes must be greater than 0',
      'errorAlarm': 'Enter a valid time',
      'newTask': 'New Task',
      'editTask': 'Edit Task',
    },
  };

  static String t(String lang, String key) => values[lang]?[key] ?? values['en']![key] ?? key;
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> with WindowListener {
  final BackendController _backend = BackendController();
  final ValueNotifier<int> _tick = ValueNotifier<int>(0);
  final SystemTray _systemTray = SystemTray();
  Timer? _ticker;
  String? _currentFolder;
  bool _compactMode = false;
  String? _lastShownError;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    _backend.addListener(_onBackendChanged);
    _backend.start();
    _initTray();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick.value++);
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _tick.dispose();
    _backend.removeListener(_onBackendChanged);
    _backend.disposeBackend();
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  void onWindowClose() async {
    if (await windowManager.isPreventClose()) {
      await windowManager.hide();
    }
  }

  void _onBackendChanged() {
    if (!mounted) return;
    final error = _backend.state.lastError;
    setState(() {});
    if (error != null && error != _lastShownError) {
      _lastShownError = error;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error), behavior: SnackBarBehavior.floating),
      );
    }
  }

  Future<void> _initTray() async {
    try {
      await _systemTray.initSystemTray(
        title: 'NativeLoopTimer',
        iconPath: Platform.isWindows ? 'assets/app_icon.ico' : 'assets/app_icon.png',
      );
      final menu = Menu();
      await menu.buildFrom([
        MenuItemLabel(label: 'Show', onClicked: (_) => windowManager.show()),
        MenuItemLabel(label: 'Pause All', onClicked: (_) => _backend.pauseAll()),
        MenuItemLabel(label: 'Resume All', onClicked: (_) => _backend.resumeAll()),
        MenuItemLabel(label: 'Mini Window', onClicked: (_) => _toggleCompactMode()),
        MenuSeparator(),
        MenuItemLabel(label: 'Exit', onClicked: (_) => _exitApp()),
      ]);
      await _systemTray.setContextMenu(menu);
      _systemTray.registerSystemTrayEventHandler((eventName) {
        if (eventName == kSystemTrayEventDoubleClick) {
          windowManager.show();
        }
      });
    } catch (_) {
      // Tray support depends on the host shell. The main app remains usable.
    }
  }

  Future<void> _exitApp() async {
    await _backend.disposeBackend();
    await windowManager.setPreventClose(false);
    await windowManager.close();
  }

  Future<void> _toggleCompactMode() async {
    _compactMode = !_compactMode;
    if (_compactMode) {
      await windowManager.setAlwaysOnTop(true);
      await windowManager.setSize(const Size(430, 620));
    } else {
      await windowManager.setAlwaysOnTop(false);
      await windowManager.setSize(const Size(1180, 760));
    }
    if (mounted) setState(() {});
  }

  List<String> _groups(AppState state) {
    final defaultGroup = Strings.t(state.language, 'defaultGroup');
    final groups = <String>{};
    for (final task in state.tasks) {
      if (task.group.trim().isNotEmpty) groups.add(task.group);
    }
    groups.remove(defaultGroup);
    final sorted = groups.toList()..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return [defaultGroup, ...sorted];
  }

  List<TimerTask> _visibleTasks(AppState state) {
    final tasks = [...state.tasks];
    if (_currentFolder == null) return const [];
    if (_currentFolder != '__all_tasks__') {
      tasks.removeWhere((task) => task.group != _currentFolder);
    }
    tasks.sort((a, b) {
      if (_currentFolder == '__all_tasks__' && a.isPaused != b.isPaused) {
        return a.isPaused ? 1 : -1;
      }
      final byOrder = a.order.compareTo(b.order);
      if (byOrder != 0) return byOrder;
      return a.createdAt.compareTo(b.createdAt);
    });
    return tasks;
  }

  @override
  Widget build(BuildContext context) {
    final state = _backend.state;
    final lang = state.language;
    final groups = _groups(state);
    final visibleTasks = _visibleTasks(state);

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _TopBar(
              title: Strings.t(lang, 'title'),
              subtitle: Strings.t(lang, 'subtitle'),
              compact: _compactMode,
              onAdd: () => _openTaskDialog(),
              onPauseAll: _backend.pauseAll,
              onResumeAll: _backend.resumeAll,
              onLanguage: () => _backend.setLanguage(lang == 'zh' ? 'en' : 'zh'),
              onCompact: _toggleCompactMode,
              lang: lang,
            ),
            Expanded(
              child: Padding(
                padding: EdgeInsets.fromLTRB(_compactMode ? 12 : 20, 8, _compactMode ? 12 : 20, 16),
                child: _currentFolder == null
                    ? _FolderView(
                        groups: groups,
                        state: state,
                        compact: _compactMode,
                        onOpenGroup: (group) => setState(() => _currentFolder = group),
                        onAllTasks: () => setState(() => _currentFolder = '__all_tasks__'),
                      )
                    : _TaskListView(
                        tasks: visibleTasks,
                        tick: _tick,
                        state: state,
                        compact: _compactMode,
                        folderTitle: _currentFolder == '__all_tasks__'
                            ? Strings.t(lang, 'allTasks')
                            : _currentFolder!,
                        onBack: () => setState(() => _currentFolder = null),
                        onPauseResume: (task) {
                          task.isPaused ? _backend.resumeTask(task.id) : _backend.pauseTask(task.id);
                        },
                        onReset: (task) => _backend.resetTask(task.id),
                        onDelete: (task) => _backend.deleteTask(task.id),
                        onEdit: (task) => _openTaskDialog(task: task),
                        onReorder: (ids) => _backend.reorderTasks(ids),
                      ),
              ),
            ),
            if (!_compactMode)
              _StatusBar(
                configPath: state.configPath,
                taskCount: state.tasks.length,
                lang: lang,
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openTaskDialog({TimerTask? task}) async {
    final state = _backend.state;
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => TaskEditorDialog(
        task: task,
        language: state.language,
        groups: _groups(state),
        soundOptions: state.soundOptions[state.language] ?? const {},
      ),
    );

    if (result == null) return;
    if (task == null) {
      _backend.createTask(result);
      setState(() => _currentFolder = result['group']?.toString());
    } else {
      _backend.updateTask(task.id, result);
    }
  }
}

class _TopBar extends StatelessWidget {
  final String title;
  final String subtitle;
  final bool compact;
  final String lang;
  final VoidCallback onAdd;
  final VoidCallback onPauseAll;
  final VoidCallback onResumeAll;
  final VoidCallback onLanguage;
  final VoidCallback onCompact;

  const _TopBar({
    required this.title,
    required this.subtitle,
    required this.compact,
    required this.lang,
    required this.onAdd,
    required this.onPauseAll,
    required this.onResumeAll,
    required this.onLanguage,
    required this.onCompact,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: compact ? 12 : 20, vertical: 14),
      decoration: const BoxDecoration(
        color: Color(0xFF0F172A),
        border: Border(bottom: BorderSide(color: Color(0xFF1F2A44))),
      ),
      child: Row(
        children: [
          const Icon(Icons.timer_outlined, color: Color(0xFF34D399), size: 28),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                if (!compact)
                  Text(subtitle, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
              ],
            ),
          ),
          _ActionButton(icon: Icons.add, label: Strings.t(lang, 'addTimer'), onPressed: onAdd),
          if (!compact) ...[
            const SizedBox(width: 8),
            _ActionButton(icon: Icons.pause, label: Strings.t(lang, 'pauseAll'), onPressed: onPauseAll),
            const SizedBox(width: 8),
            _ActionButton(icon: Icons.play_arrow, label: Strings.t(lang, 'resumeAll'), onPressed: onResumeAll),
          ],
          const SizedBox(width: 8),
          _ActionButton(icon: Icons.language, label: Strings.t(lang, 'language'), onPressed: onLanguage),
          const SizedBox(width: 8),
          IconButton.filledTonal(
            tooltip: Strings.t(lang, 'compact'),
            onPressed: onCompact,
            icon: Icon(compact ? Icons.open_in_full : Icons.picture_in_picture_alt),
          ),
        ],
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  const _ActionButton({required this.icon, required this.label, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 18),
      label: Text(label),
      style: FilledButton.styleFrom(
        minimumSize: const Size(44, 38),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
  }
}

class _FolderView extends StatelessWidget {
  final List<String> groups;
  final AppState state;
  final bool compact;
  final ValueChanged<String> onOpenGroup;
  final VoidCallback onAllTasks;

  const _FolderView({
    required this.groups,
    required this.state,
    required this.compact,
    required this.onOpenGroup,
    required this.onAllTasks,
  });

  @override
  Widget build(BuildContext context) {
    final cards = <Widget>[
      _FolderCard(
        title: Strings.t(state.language, 'allTasks'),
        count: state.tasks.length,
        icon: Icons.grid_view,
        color: const Color(0xFF38BDF8),
        onTap: onAllTasks,
      ),
      ...groups.map((group) {
        return _FolderCard(
          title: group,
          count: state.tasks.where((task) => task.group == group).length,
          icon: Icons.folder_outlined,
          color: const Color(0xFF34D399),
          onTap: () => onOpenGroup(group),
        );
      }),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final cols = compact
            ? 1
            : constraints.maxWidth >= 980
                ? 3
                : constraints.maxWidth >= 620
                    ? 2
                    : 1;
        return GridView.count(
          crossAxisCount: cols,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: compact ? 3.8 : 3.4,
          children: cards,
        );
      },
    );
  }
}

class _FolderCard extends StatelessWidget {
  final String title;
  final int count;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _FolderCard({
    required this.title,
    required this.count,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(icon, color: color),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                ),
              ),
              Text('$count', style: const TextStyle(color: Color(0xFF94A3B8), fontWeight: FontWeight.w700)),
            ],
          ),
        ),
      ),
    );
  }
}

class _TaskListView extends StatelessWidget {
  final List<TimerTask> tasks;
  final ValueNotifier<int> tick;
  final AppState state;
  final bool compact;
  final String folderTitle;
  final VoidCallback onBack;
  final ValueChanged<TimerTask> onPauseResume;
  final ValueChanged<TimerTask> onReset;
  final ValueChanged<TimerTask> onDelete;
  final ValueChanged<TimerTask> onEdit;
  final ValueChanged<List<String>> onReorder;

  const _TaskListView({
    required this.tasks,
    required this.tick,
    required this.state,
    required this.compact,
    required this.folderTitle,
    required this.onBack,
    required this.onPauseResume,
    required this.onReset,
    required this.onDelete,
    required this.onEdit,
    required this.onReorder,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            IconButton.filledTonal(
              tooltip: Strings.t(state.language, 'back'),
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                folderTitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              ),
            ),
            Text('${tasks.length}', style: const TextStyle(color: Color(0xFF94A3B8))),
          ],
        ),
        const SizedBox(height: 12),
        Expanded(
          child: tasks.isEmpty
              ? Center(
                  child: Text(
                    Strings.t(state.language, 'empty'),
                    style: const TextStyle(color: Color(0xFF94A3B8)),
                  ),
                )
              : ReorderableListView.builder(
                  buildDefaultDragHandles: false,
                  proxyDecorator: (child, index, animation) {
                    return Material(
                      color: Colors.transparent,
                      child: ScaleTransition(scale: Tween<double>(begin: 1, end: 1.02).animate(animation), child: child),
                    );
                  },
                  itemCount: tasks.length,
                  onReorderItem: (oldIndex, newIndex) {
                    final reordered = [...tasks];
                    final item = reordered.removeAt(oldIndex);
                    var insertIndex = newIndex;
                    if (insertIndex < 0) insertIndex = 0;
                    if (insertIndex > reordered.length) insertIndex = reordered.length;
                    reordered.insert(insertIndex, item);
                    onReorder(reordered.map((task) => task.id).toList());
                  },
                  itemBuilder: (context, index) {
                    final task = tasks[index];
                    return Padding(
                      key: ValueKey(task.id),
                      padding: const EdgeInsets.only(bottom: 10),
                      child: TaskCard(
                        task: task,
                        tick: tick,
                        language: state.language,
                        compact: compact,
                        index: index,
                        onPauseResume: () => onPauseResume(task),
                        onReset: () => onReset(task),
                        onEdit: () => onEdit(task),
                        onDelete: () => onDelete(task),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class TaskCard extends StatelessWidget {
  final TimerTask task;
  final ValueNotifier<int> tick;
  final String language;
  final bool compact;
  final int index;
  final VoidCallback onPauseResume;
  final VoidCallback onReset;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  const TaskCard({
    super.key,
    required this.task,
    required this.tick,
    required this.language,
    required this.compact,
    required this.index,
    required this.onPauseResume,
    required this.onReset,
    required this.onEdit,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: EdgeInsets.all(compact ? 10 : 14),
        child: Row(
          children: [
            ReorderableDragStartListener(
              index: index,
              child: SizedBox(
                width: 34,
                height: 86,
                child: Center(
                  child: Icon(Icons.drag_indicator, color: Colors.white.withValues(alpha: 0.42)),
                ),
              ),
            ),
            RepaintBoundary(
              child: ValueListenableBuilder<int>(
                valueListenable: tick,
                builder: (context, _, __) {
                  final now = DateTime.now();
                  return LiquidTimerFace(
                    progress: task.progressAt(now),
                    active: !task.isPaused,
                    alarm: task.type == TaskType.alarm,
                    size: compact ? 68 : 86,
                  );
                },
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: ValueListenableBuilder<int>(
                valueListenable: tick,
                builder: (context, _, __) {
                  final now = DateTime.now();
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            task.type == TaskType.timer ? Icons.timer_outlined : Icons.alarm,
                            size: 16,
                            color: task.isPaused ? const Color(0xFFF59E0B) : const Color(0xFF34D399),
                          ),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              task.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _statusText(task, now, language),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: task.isPaused ? const Color(0xFFFBBF24) : const Color(0xFF86EFAC),
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      if (!compact) ...[
                        const SizedBox(height: 6),
                        Text(
                          '${task.group} · ${_detailText(task, language)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                        ),
                      ],
                    ],
                  );
                },
              ),
            ),
            const SizedBox(width: 8),
            _CardButtons(
              task: task,
              language: language,
              compact: compact,
              onPauseResume: onPauseResume,
              onReset: onReset,
              onEdit: onEdit,
              onDelete: onDelete,
            ),
          ],
        ),
      ),
    );
  }

  String _statusText(TimerTask task, DateTime now, String lang) {
    if (task.isPaused) {
      if (task.type == TaskType.timer) {
        return '${Strings.t(lang, 'paused')} · ${_formatDuration(task.remainingAt(now))}';
      }
      return Strings.t(lang, 'paused');
    }
    if (task.type == TaskType.timer) {
      return '${Strings.t(lang, 'running')} · ${_formatDuration(task.remainingAt(now))}';
    }
    return '${Strings.t(lang, 'time')} ${task.alarmTime} · ${_repeatText(task, lang)}';
  }

  String _detailText(TimerTask task, String lang) {
    if (task.type == TaskType.timer) {
      final minutes = task.durationMinutes % 1 == 0 ? task.durationMinutes.toInt().toString() : task.durationMinutes.toStringAsFixed(1);
      return '$minutes ${Strings.t(lang, 'duration')}';
    }
    return _repeatText(task, lang);
  }

  String _repeatText(TimerTask task, String lang) {
    if (task.repeatDays.isEmpty) return Strings.t(lang, 'oneOff');
    const zh = ['一', '二', '三', '四', '五', '六', '日'];
    const en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    final labels = lang == 'zh' ? zh : en;
    return task.repeatDays.map((day) => labels[day - 1]).join(', ');
  }
}

class _CardButtons extends StatelessWidget {
  final TimerTask task;
  final String language;
  final bool compact;
  final VoidCallback onPauseResume;
  final VoidCallback onReset;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  const _CardButtons({
    required this.task,
    required this.language,
    required this.compact,
    required this.onPauseResume,
    required this.onReset,
    required this.onEdit,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final buttons = [
      IconButton.filledTonal(
        tooltip: task.isPaused ? Strings.t(language, 'resume') : Strings.t(language, 'pause'),
        onPressed: onPauseResume,
        icon: Icon(task.isPaused ? Icons.play_arrow : Icons.pause),
      ),
      if (task.type == TaskType.timer)
        IconButton.filledTonal(
          tooltip: Strings.t(language, 'reset'),
          onPressed: onReset,
          icon: const Icon(Icons.restart_alt),
        ),
      IconButton.filledTonal(
        tooltip: Strings.t(language, 'edit'),
        onPressed: onEdit,
        icon: const Icon(Icons.edit_outlined),
      ),
      IconButton.filledTonal(
        tooltip: Strings.t(language, 'delete'),
        onPressed: onDelete,
        icon: const Icon(Icons.delete_outline),
      ),
    ];

    if (compact) {
      return Column(mainAxisSize: MainAxisSize.min, children: buttons);
    }
    return Row(mainAxisSize: MainAxisSize.min, children: buttons);
  }
}

class LiquidTimerFace extends StatefulWidget {
  final double progress;
  final bool active;
  final bool alarm;
  final double size;

  const LiquidTimerFace({
    super.key,
    required this.progress,
    required this.active,
    required this.alarm,
    required this.size,
  });

  @override
  State<LiquidTimerFace> createState() => _LiquidTimerFaceState();
}

class _LiquidTimerFaceState extends State<LiquidTimerFace> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 1800));
    _syncAnimation();
  }

  @override
  void didUpdateWidget(covariant LiquidTimerFace oldWidget) {
    super.didUpdateWidget(oldWidget);
    _syncAnimation();
  }

  void _syncAnimation() {
    if (widget.active && !widget.alarm) {
      if (!_controller.isAnimating) _controller.repeat();
    } else {
      _controller.stop();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) {
          return CustomPaint(
            painter: LiquidTimerPainter(
              progress: widget.progress,
              phase: _controller.value * 2.0 * math.pi,
              active: widget.active,
              alarm: widget.alarm,
            ),
          );
        },
      ),
    );
  }
}

class LiquidTimerPainter extends CustomPainter {
  final double progress;
  final double phase;
  final bool active;
  final bool alarm;

  const LiquidTimerPainter({
    required this.progress,
    required this.phase,
    required this.active,
    required this.alarm,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = math.min(size.width, size.height) / 2 - 3;
    final baseColor = alarm
        ? const Color(0xFF38BDF8)
        : active
            ? const Color(0xFF34D399)
            : const Color(0xFFF59E0B);

    final bgPaint = Paint()
      ..color = const Color(0xFF0F172A)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, radius, bgPaint);

    final clipPath = Path()..addOval(Rect.fromCircle(center: center, radius: radius - 4));
    canvas.save();
    canvas.clipPath(clipPath);

    final liquidHeight = size.height * (1.0 - progress.clamp(0.0, 1.0));
    final wavePaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomCenter,
        end: Alignment.topCenter,
        colors: [
          baseColor.withValues(alpha: active ? 0.78 : 0.45),
          baseColor.withValues(alpha: active ? 0.42 : 0.20),
        ],
      ).createShader(Offset.zero & size)
      ..style = PaintingStyle.fill;

    final path = Path()..moveTo(0, size.height);
    for (double x = 0; x <= size.width; x += 2) {
      final y = liquidHeight + math.sin((x / size.width * math.pi * 2) + phase) * 4.0;
      path.lineTo(x, y);
    }
    path
      ..lineTo(size.width, size.height)
      ..close();
    canvas.drawPath(path, wavePaint);
    canvas.restore();

    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round
      ..color = const Color(0xFF334155);
    canvas.drawCircle(center, radius, ringPaint);

    final progressPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.round
      ..color = baseColor;
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -math.pi / 2,
      math.pi * 2 * progress.clamp(0.0, 1.0),
      false,
      progressPaint,
    );

    final iconPainter = TextPainter(
      text: TextSpan(
        text: alarm ? String.fromCharCode(Icons.alarm.codePoint) : String.fromCharCode(Icons.timer_outlined.codePoint),
        style: TextStyle(
          fontFamily: Icons.alarm.fontFamily,
          package: Icons.alarm.fontPackage,
          color: Colors.white.withValues(alpha: 0.92),
          fontSize: size.width * 0.32,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    iconPainter.paint(canvas, center - Offset(iconPainter.width / 2, iconPainter.height / 2));
  }

  @override
  bool shouldRepaint(covariant LiquidTimerPainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.phase != phase ||
        oldDelegate.active != active ||
        oldDelegate.alarm != alarm;
  }
}

class TaskEditorDialog extends StatefulWidget {
  final TimerTask? task;
  final String language;
  final List<String> groups;
  final Map<String, String> soundOptions;

  const TaskEditorDialog({
    super.key,
    required this.task,
    required this.language,
    required this.groups,
    required this.soundOptions,
  });

  @override
  State<TaskEditorDialog> createState() => _TaskEditorDialogState();
}

class _TaskEditorDialogState extends State<TaskEditorDialog> {
  late TaskType _type;
  late TextEditingController _nameController;
  late TextEditingController _groupController;
  late TextEditingController _durationController;
  late TextEditingController _hourController;
  late TextEditingController _minuteController;
  late bool _autoLoop;
  late Set<int> _repeatDays;
  late String _soundPath;
  String? _error;

  @override
  void initState() {
    super.initState();
    final task = widget.task;
    _type = task?.type ?? TaskType.timer;
    _nameController = TextEditingController(text: task?.name ?? '');
    _groupController = TextEditingController(
      text: task?.group ?? (widget.groups.isNotEmpty ? widget.groups.first : Strings.t(widget.language, 'defaultGroup')),
    );
    _durationController = TextEditingController(text: task == null ? '20' : _formatNumber(task.durationMinutes));
    final alarmTime = task?.alarmTime ?? '08:30';
    final parts = alarmTime.split(':');
    _hourController = TextEditingController(text: parts.isNotEmpty ? parts[0] : '08');
    _minuteController = TextEditingController(text: parts.length > 1 ? parts[1] : '30');
    _autoLoop = task?.isAutoLoop ?? true;
    _repeatDays = {...?task?.repeatDays};
    _soundPath = task?.soundPath ?? _defaultSoundPath(widget.soundOptions);
  }

  @override
  void dispose() {
    _nameController.dispose();
    _groupController.dispose();
    _durationController.dispose();
    _hourController.dispose();
    _minuteController.dispose();
    super.dispose();
  }

  String _defaultSoundPath(Map<String, String> soundOptions) {
    return soundOptions.entries
        .firstWhere(
          (entry) =>
              entry.key.toLowerCase().contains('warm ding') ||
              entry.value.toLowerCase().endsWith('/ding.wav'),
          orElse: () => soundOptions.entries.isNotEmpty
              ? soundOptions.entries.first
              : const MapEntry('', 'C:/Windows/Media/ding.wav'),
        )
        .value;
  }

  @override
  Widget build(BuildContext context) {
    final lang = widget.language;
    final isEditing = widget.task != null;
    return AlertDialog(
      title: Text(isEditing ? Strings.t(lang, 'editTask') : Strings.t(lang, 'newTask')),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!isEditing)
                Row(
                  children: [
                    ChoiceChip(
                      label: Text(Strings.t(lang, 'timer')),
                      selected: _type == TaskType.timer,
                      onSelected: (_) => setState(() => _type = TaskType.timer),
                    ),
                    const SizedBox(width: 8),
                    ChoiceChip(
                      label: Text(Strings.t(lang, 'alarm')),
                      selected: _type == TaskType.alarm,
                      onSelected: (_) => setState(() => _type = TaskType.alarm),
                    ),
                  ],
                ),
              if (!isEditing) const SizedBox(height: 14),
              TextField(
                controller: _nameController,
                decoration: InputDecoration(labelText: Strings.t(lang, 'name')),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _groupController,
                decoration: InputDecoration(labelText: Strings.t(lang, 'group')),
              ),
              const SizedBox(height: 12),
              if (_type == TaskType.timer) ...[
                TextField(
                  controller: _durationController,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
                  decoration: InputDecoration(labelText: Strings.t(lang, 'duration')),
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(Strings.t(lang, 'autoLoop')),
                  value: _autoLoop,
                  onChanged: (value) => setState(() => _autoLoop = value ?? true),
                ),
              ] else ...[
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _hourController,
                        keyboardType: TextInputType.number,
                        inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(2)],
                        decoration: InputDecoration(labelText: '${Strings.t(lang, 'time')} HH'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: _minuteController,
                        keyboardType: TextInputType.number,
                        inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(2)],
                        decoration: const InputDecoration(labelText: 'MM'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(Strings.t(lang, 'repeat'), style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: List.generate(7, (index) {
                    const zh = ['一', '二', '三', '四', '五', '六', '日'];
                    const en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
                    final day = index + 1;
                    return FilterChip(
                      label: Text(lang == 'zh' ? zh[index] : en[index]),
                      selected: _repeatDays.contains(day),
                      onSelected: (selected) {
                        setState(() {
                          selected ? _repeatDays.add(day) : _repeatDays.remove(day);
                        });
                      },
                    );
                  }),
                ),
              ],
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: widget.soundOptions.containsValue(_soundPath) ? _soundPath : null,
                decoration: InputDecoration(labelText: Strings.t(lang, 'sound')),
                items: widget.soundOptions.entries.map((entry) {
                  return DropdownMenuItem(value: entry.value, child: Text(entry.key));
                }).toList(),
                onChanged: (value) {
                  if (value != null) setState(() => _soundPath = value);
                },
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Color(0xFFF87171))),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(Strings.t(lang, 'cancel')),
        ),
        FilledButton(
          onPressed: _submit,
          child: Text(Strings.t(lang, 'save')),
        ),
      ],
    );
  }

  void _submit() {
    final lang = widget.language;
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = Strings.t(lang, 'errorName'));
      return;
    }
    final group = _groupController.text.trim().isEmpty
        ? Strings.t(lang, 'defaultGroup')
        : _groupController.text.trim();

    final payload = <String, dynamic>{
      'name': name,
      'group': group,
      'sound_path': _soundPath,
    };

    if (widget.task == null) {
      payload['type'] = _taskTypeToString(_type);
    }

    if (_type == TaskType.timer) {
      final duration = double.tryParse(_durationController.text.trim());
      if (duration == null || duration <= 0) {
        setState(() => _error = Strings.t(lang, 'errorDuration'));
        return;
      }
      payload['duration_minutes'] = duration;
      payload['is_auto_loop'] = _autoLoop;
    } else {
      final hour = int.tryParse(_hourController.text.trim());
      final minute = int.tryParse(_minuteController.text.trim());
      if (hour == null || minute == null || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
        setState(() => _error = Strings.t(lang, 'errorAlarm'));
        return;
      }
      payload['alarm_time'] = '${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}';
      payload['repeat_days'] = _repeatDays.toList()..sort();
    }

    Navigator.pop(context, payload);
  }

  String _formatNumber(double value) {
    return value % 1 == 0 ? value.toInt().toString() : value.toStringAsFixed(1);
  }
}

class _StatusBar extends StatelessWidget {
  final String configPath;
  final int taskCount;
  final String lang;

  const _StatusBar({required this.configPath, required this.taskCount, required this.lang});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 34,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: const BoxDecoration(
        color: Color(0xFF0F172A),
        border: Border(top: BorderSide(color: Color(0xFF1F2A44))),
      ),
      child: Row(
        children: [
          Text('$taskCount tasks', style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
          const Spacer(),
          if (configPath.isNotEmpty)
            Flexible(
              child: Text(
                '${Strings.t(lang, 'config')}: $configPath',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Color(0xFF64748B), fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

String _formatDuration(double seconds) {
  final safe = math.max(0, seconds.round());
  final hours = safe ~/ 3600;
  final minutes = (safe % 3600) ~/ 60;
  final secs = safe % 60;
  if (hours > 0) {
    return '${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
  }
  return '${minutes.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
}
