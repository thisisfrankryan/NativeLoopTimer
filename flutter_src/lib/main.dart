import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:window_manager/window_manager.dart';
import 'package:system_tray/system_tray.dart';
import 'assets_manager.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  // Initialize desktop window manager configurations
  await windowManager.ensureInitialized();
  WindowOptions windowOptions = const WindowOptions(
    size: Size(420, 680),
    minimumSize: Size(420, 680),
    center: true,
    backgroundColor: Colors.transparent,
    skipTaskbar: false,
    titleBarStyle: TitleBarStyle.normal,
  );
  
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
    // Intercept default window exit to redirect to system tray minimize
    await windowManager.setPreventClose(true);
  });

  runApp(const NativeLoopTimerApp());
}

class NativeLoopTimerApp extends StatelessWidget {
  const NativeLoopTimerApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return FluentApp(
      title: 'NativeLoopTimer',
      themeMode: ThemeMode.dark,
      darkTheme: FluentThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0F172A), // Premium Dark Slate/Navy background
        accentColor: SystemAccentColor.accent[AccentColor.green],
      ),
      home: const DashboardPage(),
    );
  }
}

class DashboardPage extends StatefulWidget {
  const DashboardPage({Key? key}) : super(key: key);

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> with WindowListener, SingleTickerProviderStateMixin {
  // UI & Animation controllers
  late AnimationController _breathingController;
  double _timerDurationMinutes = 20.0;
  bool _isLightweightMode = false;
  bool _isTicking = false;
  bool _isPaused = false;
  int _remainingSeconds = 1200;
  
  // Headless Python Process managers
  Process? _normalBackendProcess;
  String? _cachedBackendPath;
  final SystemTray _systemTray = SystemTray();
  
  // Transition overlay states
  bool _showLightweightTransition = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    
    // Smooth breathing gradient animation for the countdown ring
    _breathingController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);

    _initAppEnvironment();
  }

  Future<void> _initAppEnvironment() async {
    try {
      // 1. Unpack assets/backend.exe to sandbox
      final path = await AssetsManager.extractBackend();
      setState(() {
        _cachedBackendPath = path;
      });

      // 2. Register tray notification icon
      await _initSystemTray();
      
      // 3. Spawn normal mode background process initially
      await _spawnNormalBackend();
    } catch (e) {
      _showErrorDialog("初始化失败: $e");
    }
  }

  Future<void> _initSystemTray() async {
    final AppWindow appWindow = AppWindow();
    
    // Choose appropriate notification tray icon (bundle path or dynamic icon)
    await _systemTray.initSystemTray(
      title: "NativeLoopTimer",
      iconPath: Platform.isWindows ? 'assets/app_icon.ico' : 'assets/app_icon.png',
    );

    final Menu menu = Menu();
    await menu.buildFrom([
      MenuItemLabel(label: '显示控制台', onClicked: (menuItem) => windowManager.show()),
      MenuItemLabel(label: '暂停计时', onClicked: (menuItem) => _pauseTimer()),
      MenuItemLabel(label: '恢复计时', onClicked: (menuItem) => _resumeTimer()),
      MenuItemLabel(label: '结束计时', onClicked: (menuItem) => _stopTimer()),
      MenuSeparator(),
      MenuItemLabel(label: '彻底退出', onClicked: (menuItem) => _forceExitApplication()),
    ]);

    await _systemTray.setContextMenu(menu);
    _systemTray.registerSystemTrayEventHandler((eventName) {
      if (eventName == kSystemTrayEventDoubleClick) {
        windowManager.show();
      }
    });
  }

  Future<void> _spawnNormalBackend() async {
    if (_cachedBackendPath == null) return;
    
    // Kill any existing normal backend process
    _normalBackendProcess?.kill();

    // Spawn Python backend daemon in headless mode (no CMD window popup)
    _normalBackendProcess = await Process.start(
      _cachedBackendPath!,
      [],
      runInShell: false,
    );

    // Stream parse stdin/stdout JSON status packets
    _normalBackendProcess!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((String line) {
          try {
            final packet = jsonDecode(line.strip());
            final status = packet['status'];
            
            if (status == 'tick') {
              setState(() {
                _remainingSeconds = packet['remaining'] as int;
                _isPaused = packet['is_paused'] as bool;
                _isTicking = true;
              });
            } else if (status == 'expired') {
              setState(() {
                _isTicking = false;
                _isPaused = false;
              });
            }
          } catch (_) {
            // Ignore corrupted lines
          }
        });
  }

  // Intercept close behavior: Hide window instead of exiting
  @override
  void onWindowClose() async {
    bool isPreventClose = await windowManager.isPreventClose();
    if (isPreventClose) {
      await windowManager.hide();
    }
  }

  Future<void> _startTimer() async {
    final seconds = (_timerDurationMinutes * 60).toInt();

    if (_isLightweightMode) {
      // 1. Spawns backend in DETACHED independent mode
      if (_cachedBackendPath == null) return;
      
      // Kill regular child process to prevent collisions
      _normalBackendProcess?.kill();
      _normalBackendProcess = null;

      // Start completely detached daemon with stdout/stdin pipes redirected
      final detachedProcess = await Process.start(
        _cachedBackendPath!,
        [],
        mode: ProcessStartMode.detachedWithStdio,
      );

      // Write start action command into detached standard input
      detachedProcess.stdin.write(jsonEncode({
        "action": "start",
        "duration": seconds
      }) + "\n");
      await detachedProcess.stdin.flush();
      
      // Detached process is completely orphan, standard pipe will close on exit.
      detachedProcess.stdin.close();

      // Show high-end glassmorphism overlay transition
      setState(() {
        _showLightweightTransition = true;
      });

      // Exit Flutter after 3 seconds to release all graphic/RAM resources
      Future.delayed(const Duration(seconds: 3), () {
        SystemNavigator.pop();
        exit(0);
      });
      
    } else {
      // Normal Mode Timer
      if (_normalBackendProcess == null) {
        await _spawnNormalBackend();
      }
      
      _normalBackendProcess!.stdin.write(jsonEncode({
        "action": "start",
        "duration": seconds
      }) + "\n");
      await _normalBackendProcess!.stdin.flush();
      
      setState(() {
        _isTicking = true;
        _isPaused = false;
        _remainingSeconds = seconds;
      });
    }
  }

  Future<void> _pauseTimer() async {
    _normalBackendProcess?.stdin.write(jsonEncode({"action": "pause"}) + "\n");
    await _normalBackendProcess?.stdin.flush();
  }

  Future<void> _resumeTimer() async {
    _normalBackendProcess?.stdin.write(jsonEncode({"action": "resume"}) + "\n");
    await _normalBackendProcess?.stdin.flush();
  }

  Future<void> _stopTimer() async {
    _normalBackendProcess?.stdin.write(jsonEncode({"action": "stop"}) + "\n");
    await _normalBackendProcess?.stdin.flush();
    setState(() {
      _isTicking = false;
      _isPaused = false;
    });
  }

  Future<void> _forceExitApplication() async {
    // Gracefully stop python backend, close window listeners, and terminate
    _normalBackendProcess?.kill();
    await windowManager.setPreventClose(false);
    await windowManager.close();
  }

  void _showErrorDialog(String msg) {
    showDialog(
      context: context,
      builder: (context) => ContentDialog(
        title: const Text('系统提示'),
        content: Text(msg),
        actions: [
          Button(
            child: const Text('确定'),
            onPressed: () => Navigator.pop(context),
          )
        ],
      ),
    );
  }

  String _formatDisplayTime(int totalSecs) {
    final m = totalSecs ~/ 60;
    final s = totalSecs % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  @override
  void dispose() {
    _normalBackendProcess?.kill();
    _breathingController.dispose();
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final double percent = _isTicking
        ? _remainingSeconds / (_timerDurationMinutes * 60)
        : 1.0;

    return ScaffoldPage(
      content: Stack(
        children: [
          // Main controls layout
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 30),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const SizedBox(height: 20),
                const Text(
                  'NativeLoopTimer',
                  style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: Colors.white),
                ),
                const SizedBox(height: 5),
                Text(
                  _isTicking 
                      ? (_isPaused ? '计时暂停中' : '专注工作中，请保持姿势') 
                      : '配置您的专注时间',
                  style: const TextStyle(fontSize: 13, color: Color(0xFF94A3B8)),
                ),
                const SizedBox(height: 40),

                // Animated Circular Countdown Progress Ring
                Center(
                  child: AnimatedBuilder(
                    animation: _breathingController,
                    builder: (context, child) {
                      // Dynamically compute neon glow size using breathing animation
                      final glow = _isTicking && !_isPaused 
                          ? 6.0 + 4.0 * _breathingController.value 
                          : 6.0;
                      return Container(
                        width: 250,
                        height: 250,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          boxShadow: [
                            BoxShadow(
                              color: const Color(0xFF10B981).withOpacity(0.15),
                              blurRadius: glow,
                              spreadRadius: glow / 2,
                            )
                          ],
                        ),
                        child: child,
                      );
                    },
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // Background track circle
                        SizedBox(
                          width: 230,
                          height: 230,
                          child: CircularProgressIndicator(
                            value: 1.0,
                            strokeWidth: 6,
                            backgroundColor: const Color(0xFF1E293B),
                          ),
                        ),
                        // Foreground progress circle
                        SizedBox(
                          width: 230,
                          height: 230,
                          child: CircularProgressIndicator(
                            value: percent,
                            strokeWidth: 8,
                            backgroundColor: Colors.transparent,
                            color: const Color(0xFF10B981),
                          ),
                        ),
                        // Remainder timer text
                        Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(
                              _isTicking 
                                  ? _formatDisplayTime(_remainingSeconds) 
                                  : '${_timerDurationMinutes.toInt()}:00',
                              style: const TextStyle(
                                fontSize: 44, 
                                fontWeight: FontWeight.bold, 
                                color: Colors.white,
                                fontFamily: 'Consolas',
                              ),
                            ),
                            const SizedBox(height: 5),
                            Text(
                              '设定: ${_timerDurationMinutes.toInt()}分钟',
                              style: const TextStyle(fontSize: 12, color: Color(0xFF94A3B8)),
                            )
                          ],
                        )
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 40),

                // Slider settings (disabled during countdown ticks)
                Slider(
                  value: _timerDurationMinutes,
                  min: 5.0,
                  max: 120.0,
                  divisions: 23,
                  label: '${_timerDurationMinutes.toInt()}分钟',
                  onChanged: _isTicking
                      ? null
                      : (val) {
                          setState(() {
                            _timerDurationMinutes = val;
                          });
                        },
                ),
                const SizedBox(height: 30),

                // Extreme Lightweight Mode Switch
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: const Color(0xFF334155)),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: const [
                          Text('极致轻量模式', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white)),
                          SizedBox(height: 2),
                          Text('启动后关闭界面，仅Python内核后台运行', style: TextStyle(fontSize: 11, color: Color(0xFF94A3B8))),
                        ],
                      ),
                      ToggleSwitch(
                        checked: _isLightweightMode,
                        onChanged: _isTicking
                            ? null
                            : (val) {
                                setState(() {
                                  _isLightweightMode = val;
                                });
                              },
                      )
                    ],
                  ),
                ),
                const Spacer(),

                // Action buttons row
                Row(
                  children: [
                    if (!_isTicking)
                      Expanded(
                        child: FilledButton(
                          child: const Text('开始专注', style: TextStyle(fontWeight: FontWeight.bold)),
                          onPressed: _startTimer,
                        ),
                      )
                    else ...[
                      Expanded(
                        child: Button(
                          child: Text(_isPaused ? '恢复' : '暂停', style: const TextStyle(fontWeight: FontWeight.bold)),
                          onPressed: _isPaused ? _resumeTimer : _pauseTimer,
                        ),
                      ),
                      const SizedBox(width: 15),
                      Expanded(
                        child: FilledButton(
                          style: ButtonStyle(
                            backgroundColor: ButtonState.all(const Color(0xFFEF4444)),
                          ),
                          child: const Text('放弃', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.white)),
                          onPressed: _stopTimer,
                        ),
                      )
                    ]
                  ],
                ),
                const SizedBox(height: 10),
              ],
            ),
          ),

          // High-end glassmorphism transition overlay (For extreme lightweight mode transition)
          if (_showLightweightTransition)
            Positioned.fill(
              child: Container(
                color: const Color(0xFF090D16).withOpacity(0.85),
                child: Center(
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 30),
                    padding: const EdgeInsets.all(25),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E293B).withOpacity(0.7),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: const Color(0xFF334155).withOpacity(0.5)),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: const [
                        ProgressRing(color: Color(0xFF10B981)),
                        SizedBox(height: 20),
                        Text(
                          'NativeLoopTimer',
                          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white),
                        ),
                        SizedBox(height: 10),
                        Text(
                          '已进入极致轻量模式，前端界面已安全退出，Python后台内核持续守护计时中...',
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: 13, color: Color(0xFF94A3B8), height: 1.5),
                        )
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
extension on String {
  String strip() => trim();
}
