import 'dart:convert';
import 'dart:io';
import 'dart:ui';
import 'dart:math' as math;
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
    size: Size(430, 720),
    minimumSize: Size(430, 720),
    center: true,
    backgroundColor: Colors.transparent,
    skipTaskbar: false,
    titleBarStyle: TitleBarStyle.normal,
  );
  
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
    // Intercept default window close to minimize to tray
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
        scaffoldBackgroundColor: const Color(0xFF090D16), // Deep cosmos black for fluid contrast
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

class _DashboardPageState extends State<DashboardPage> with WindowListener, TickerProviderStateMixin {
  // Animation controllers for morphing fluid background and breathing timer bubble
  late AnimationController _breathingController;
  late AnimationController _fluidController1;
  late AnimationController _fluidController2;
  late AnimationController _fluidController3;
  late AnimationController _fluidController4;
  
  double _timerDurationMinutes = 20.0;
  bool _isLightweightMode = false;
  bool _isTicking = false;
  bool _isPaused = false;
  int _remainingSeconds = 1200;
  
  Process? _normalBackendProcess;
  String? _cachedBackendPath;
  final SystemTray _systemTray = SystemTray();
  
  bool _showLightweightTransition = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    
    // Pulse animation for the core liquid countdown bubble
    _breathingController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);

    // Floating background fluid blob animation 1 (slow circular morphing)
    _fluidController1 = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat(reverse: true);

    // Floating background fluid blob animation 2
    _fluidController2 = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 12),
    )..repeat(reverse: true);

    // Floating background fluid blob animation 3
    _fluidController3 = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 15),
    )..repeat(reverse: true);

    // Floating background fluid blob animation 4
    _fluidController4 = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 20),
    )..repeat(reverse: true);

    _initAppEnvironment();
  }

  Future<void> _initAppEnvironment() async {
    try {
      final path = await AssetsManager.extractBackend();
      setState(() {
        _cachedBackendPath = path;
      });

      await _initSystemTray();
      await _spawnNormalBackend();
    } catch (e) {
      _showErrorDialog("初始化失败: $e");
    }
  }

  Future<void> _initSystemTray() async {
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
    _normalBackendProcess?.kill();

    _normalBackendProcess = await Process.start(
      _cachedBackendPath!,
      [],
      runInShell: false,
    );

    _normalBackendProcess!.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((String line) {
          try {
            final packet = jsonDecode(line.trim());
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
          } catch (_) {}
        });
  }

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
      if (_cachedBackendPath == null) return;
      _normalBackendProcess?.kill();
      _normalBackendProcess = null;

      final detachedProcess = await Process.start(
        _cachedBackendPath!,
        [],
        mode: ProcessStartMode.detachedWithStdio,
      );

      detachedProcess.stdin.write(jsonEncode({
        "action": "start",
        "duration": seconds
      }) + "\n");
      await detachedProcess.stdin.flush();
      detachedProcess.stdin.close();

      setState(() {
        _showLightweightTransition = true;
      });

      Future.delayed(const Duration(seconds: 3), () {
        SystemNavigator.pop();
        exit(0);
      });
      
    } else {
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
    _fluidController1.dispose();
    _fluidController2.dispose();
    _fluidController3.dispose();
    _fluidController4.dispose();
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final double percent = _isTicking
        ? _remainingSeconds / (_timerDurationMinutes * 60)
        : 1.0;

    return ScaffoldPage(
      padding: EdgeInsets.zero,
      content: Stack(
        children: [
          // 🌌 Liquid Cosmos Background: Morphing glowing colorful blobs
          Positioned.fill(
            child: Container(
              color: const Color(0xFF070A13),
            ),
          ),
          
          // Blob 1: Mint Green glowing liquid blob moving slowly
          AnimatedBuilder(
            animation: _fluidController1,
            builder: (context, child) {
              final x = 40.0 + 80.0 * _fluidController1.value;
              final y = 80.0 + 120.0 * (1.0 - _fluidController1.value);
              return Positioned(
                left: x,
                top: y,
                child: Container(
                  width: 280,
                  height: 280,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xFF10B981).withOpacity(0.24), // Glowing Emerald
                        const Color(0xFF047857).withOpacity(0.08),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              );
            },
          ),

          // Blob 2: Deep Neon Cyan glowing liquid blob morphing diagonally
          AnimatedBuilder(
            animation: _fluidController2,
            builder: (context, child) {
              final x = 120.0 - 90.0 * _fluidController2.value;
              final y = 300.0 + 150.0 * _fluidController2.value;
              return Positioned(
                left: x,
                top: y,
                child: Container(
                  width: 340,
                  height: 340,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xFF06B6D4).withOpacity(0.22), // Glowing Cyan
                        const Color(0xFF0891B2).withOpacity(0.06),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              );
            },
          ),

          // Blob 3: Orchid Hot Pink glowing liquid blob morphing oppositely
          AnimatedBuilder(
            animation: _fluidController3,
            builder: (context, child) {
              final x = 200.0 + 120.0 * _fluidController3.value;
              final y = 150.0 - 130.0 * _fluidController3.value;
              return Positioned(
                left: x,
                top: y,
                child: Container(
                  width: 260,
                  height: 260,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xFFEC4899).withOpacity(0.20), // Glowing Hot Pink
                        const Color(0xFFBE185D).withOpacity(0.05),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              );
            },
          ),

          // Blob 4: Sunset Amber glowing liquid blob morphing at the bottom
          AnimatedBuilder(
            animation: _fluidController4,
            builder: (context, child) {
              final x = 80.0 + 170.0 * (1.0 - _fluidController4.value);
              final y = 450.0 + 130.0 * _fluidController4.value;
              return Positioned(
                left: x,
                top: y,
                child: Container(
                  width: 300,
                  height: 300,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        const Color(0xFFF59E0B).withOpacity(0.18), // Glowing Amber
                        const Color(0xFFB45309).withOpacity(0.04),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              );
            },
          ),

          // 🥛 Apple Liquid Glass Frost Container
          Positioned.fill(
            child: BackdropFilter(
              filter: ImageFilter.blur(sigmaX: 35.0, sigmaY: 35.0), // High gloss frosting blur
              child: Container(
                color: const Color(0xFF090D16).withOpacity(0.45), // Premium cosmos dark tint overlay
              ),
            ),
          ),

          // Main Glassmorphism Dashboard Layout
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 35, vertical: 25),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const SizedBox(height: 10),
                  // Apple-style Minimal Header
                  const Text(
                    'NativeLoopTimer',
                    style: TextStyle(
                      fontSize: 30, 
                      fontWeight: FontWeight.w900, 
                      color: Colors.white,
                      letterSpacing: -0.8,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.04),
                      borderRadius: BorderRadius.circular(100),
                      border: Border.all(color: Colors.white.withOpacity(0.12), width: 1.0),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.1),
                          blurRadius: 4,
                        )
                      ],
                    ),
                    child: Text(
                      _isTicking 
                          ? (_isPaused ? '⏸️ 专注已暂停' : '🟢 深度专注中') 
                          : '💤 待命',
                      style: TextStyle(
                        fontSize: 11, 
                        fontWeight: FontWeight.w800,
                        color: _isTicking && !_isPaused ? const Color(0xFF00FF87) : const Color(0xFF94A3B8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 35),

                  // 🔮 Dynamic Apple Liquid Glass Bubble (Floating Circle)
                  Center(
                    child: AnimatedBuilder(
                      animation: _breathingController,
                      builder: (context, child) {
                        final pulse = _isTicking && !_isPaused 
                            ? _breathingController.value 
                            : 0.0;
                        final glowSize = 18.0 + 15.0 * pulse;
                        
                        // Select glow/border colors dynamically based on states
                        final Color activeGlowColor = _isTicking 
                            ? (_isPaused ? const Color(0xFF00C6FF) : const Color(0xFF00FF87)) 
                            : const Color(0xFF8B5CF6);
                            
                        return Container(
                          width: 245,
                          height: 245,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(
                                color: activeGlowColor.withOpacity(0.15 + 0.10 * pulse),
                                blurRadius: glowSize,
                                spreadRadius: glowSize / 4,
                              )
                            ],
                            gradient: LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [
                                Colors.white.withOpacity(0.15), // High-sheen top highlight border
                                Colors.white.withOpacity(0.01),
                              ],
                            ),
                            border: Border.all(
                              color: Colors.white.withOpacity(0.25 + 0.15 * pulse), // Glossy rim
                              width: 1.5,
                            ),
                          ),
                          child: child,
                        );
                      },
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          // 1. Wavy Animated Liquid Layer inside
                          Positioned.fill(
                            child: ClipOval(
                              child: AnimatedBuilder(
                                animation: _breathingController,
                                builder: (context, child) {
                                  // Use the pulse breathing controller value mapped to 2*PI for fluid wave animation
                                  final double phase = _breathingController.value * 2 * math.pi;
                                  
                                  // Choose wave gradients based on state
                                  final Color waveStart;
                                  final Color waveEnd;
                                  if (_isTicking) {
                                    if (_isPaused) {
                                      // Paused: Calm Slate to Cyan
                                      waveStart = const Color(0xFF00C6FF).withOpacity(0.6);
                                      waveEnd = const Color(0xFF0072FF).withOpacity(0.4);
                                    } else {
                                      // Active: Vibrant Emerald to Cyan
                                      waveStart = const Color(0xFF00FF87).withOpacity(0.7);
                                      waveEnd = const Color(0xFF60EFFF).withOpacity(0.45);
                                    }
                                  } else {
                                    // Stopped / Idle: Deep Indigo Royal Glass
                                    waveStart = const Color(0xFF8B5CF6).withOpacity(0.35);
                                    waveEnd = const Color(0xFF3B82F6).withOpacity(0.15);
                                  }
                                  
                                  return CustomPaint(
                                    painter: LiquidWavePainter(
                                      percent: percent,
                                      wavePhase: phase,
                                      colorStart: waveStart,
                                      colorEnd: waveEnd,
                                    ),
                                  );
                                },
                              ),
                            ),
                          ),

                          // 2. High-contrast translucent glass blur backplate for readability
                          ClipOval(
                            child: BackdropFilter(
                              filter: ImageFilter.blur(sigmaX: 8.0, sigmaY: 8.0),
                              child: Container(
                                width: 175,
                                height: 175,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: Colors.black.withOpacity(0.22),
                                  border: Border.all(
                                    color: Colors.white.withOpacity(0.08),
                                    width: 1.0,
                                  ),
                                ),
                              ),
                            ),
                          ),

                          // 3. Backing grey progress ring track
                          SizedBox(
                            width: 215,
                            height: 215,
                            child: CircularProgressIndicator(
                              value: 1.0,
                              strokeWidth: 4,
                              backgroundColor: Colors.white.withOpacity(0.06),
                            ),
                          ),

                          // 4. Glowing Liquid Progress Ring Indicator
                          SizedBox(
                            width: 215,
                            height: 215,
                            child: CircularProgressIndicator(
                              value: percent,
                              strokeWidth: 6,
                              backgroundColor: Colors.transparent,
                              color: _isTicking 
                                  ? (_isPaused ? const Color(0xFF00C6FF) : const Color(0xFF00FF87)) 
                                  : const Color(0xFF8B5CF6),
                            ),
                          ),

                          // 5. Specular Gloss Reflection Layer (Top Crescent)
                          Positioned(
                            top: 8,
                            child: Container(
                              width: 150,
                              height: 65,
                              decoration: BoxDecoration(
                                borderRadius: const BorderRadius.all(Radius.elliptical(120, 50)),
                                gradient: LinearGradient(
                                  begin: Alignment.topCenter,
                                  end: Alignment.bottomCenter,
                                  colors: [
                                    Colors.white.withOpacity(0.38), // High gloss highlight sheen
                                    Colors.white.withOpacity(0.0),
                                  ],
                                ),
                              ),
                            ),
                          ),

                          // 6. Ambient Bounce Light Reflection (Bottom)
                          Positioned(
                            bottom: 12,
                            child: Container(
                              width: 140,
                              height: 35,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                gradient: RadialGradient(
                                  colors: [
                                    _isTicking 
                                        ? (_isPaused ? const Color(0xFF00C6FF).withOpacity(0.16) : const Color(0xFF00FF87).withOpacity(0.18))
                                        : const Color(0xFF8B5CF6).withOpacity(0.14),
                                    Colors.transparent,
                                  ],
                                ),
                              ),
                            ),
                          ),

                          // 7. Central Countdown Clock Labels
                          Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Text(
                                _isTicking 
                                    ? _formatDisplayTime(_remainingSeconds) 
                                    : '${_timerDurationMinutes.toInt()}:00',
                                style: const TextStyle(
                                  fontSize: 46, 
                                  fontWeight: FontWeight.w900, 
                                  color: Colors.white,
                                  letterSpacing: -1,
                                  fontFamily: 'Consolas',
                                  shadows: [
                                    Shadow(
                                      color: Colors.black,
                                      blurRadius: 4.0,
                                      offset: Offset(0, 2),
                                    )
                                  ]
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '设定: ${_timerDurationMinutes.toInt()}分钟',
                                style: TextStyle(
                                  fontSize: 11, 
                                  fontWeight: FontWeight.w700,
                                  color: Colors.white.withOpacity(0.55),
                                  shadows: const [
                                    Shadow(
                                      color: Colors.black,
                                      blurRadius: 2.0,
                                      offset: Offset(0, 1),
                                    )
                                  ]
                                ),
                              )
                            ],
                          )
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 45),

                  // 🎚️ Liquid Glass Time Slider Capsule
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.02),
                      borderRadius: BorderRadius.circular(100),
                      border: Border.all(color: Colors.white.withOpacity(0.12), width: 1.0),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.12),
                          blurRadius: 8,
                          offset: const Offset(0, 3),
                        )
                      ],
                    ),
                    child: Row(
                      children: [
                        const Text(
                          '⏱️',
                          style: TextStyle(fontSize: 14),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Slider(
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
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 25),

                  // 🧪 Extreme Lightweight Mode Liquid-Glass Toggle Capsule
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                        colors: [
                          Colors.white.withOpacity(0.05),
                          Colors.white.withOpacity(0.01),
                        ],
                      ),
                      borderRadius: BorderRadius.circular(22),
                      border: Border.all(color: Colors.white.withOpacity(0.14), width: 1.0),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.18),
                          blurRadius: 12,
                          offset: const Offset(0, 4),
                        )
                      ],
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              '极致轻量化挂机',
                              style: TextStyle(
                                fontSize: 14, 
                                fontWeight: FontWeight.w800, 
                                color: Colors.white,
                                letterSpacing: -0.1,
                              ),
                            ),
                            const SizedBox(height: 3),
                            Text(
                              '启动后Flutter自动销毁，极低内存守护',
                              style: TextStyle(fontSize: 11, color: Colors.white.withOpacity(0.45)),
                            ),
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

                  // 🌟 Fluid-style Neon Capsule Action Buttons
                  Row(
                    children: [
                      if (!_isTicking)
                        Expanded(
                          child: AquaGelButton(
                            label: '开始专注时间',
                            baseColor: const Color(0xFF10B981), // Emerald
                            shadowColor: const Color(0xFF10B981),
                            icon: '▶',
                            onPressed: _startTimer,
                          ),
                        )
                      else ...[
                        Expanded(
                          child: AquaGelButton(
                            label: _isPaused ? '恢复计时' : '暂停计时',
                            baseColor: _isPaused ? const Color(0xFF3B82F6) : const Color(0xFF64748B), // Slate / Cyan Blue
                            shadowColor: _isPaused ? const Color(0xFF3B82F6) : const Color(0xFF64748B),
                            icon: _isPaused ? '▶' : '⏸',
                            onPressed: _isPaused ? _resumeTimer : _pauseTimer,
                          ),
                        ),
                        const SizedBox(width: 15),
                        Expanded(
                          child: AquaGelButton(
                            label: '放弃专注',
                            baseColor: const Color(0xFFEF4444), // Ruby Red
                            shadowColor: const Color(0xFFEF4444),
                            icon: '⏹',
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
          ),

          // 🧊 3D Liquid-Glass Transition Modal (For lightweight mode transition)
          if (_showLightweightTransition)
            Positioned.fill(
              child: Container(
                color: const Color(0xFF05080E).withOpacity(0.85),
                child: Center(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(28),
                    child: BackdropFilter(
                      filter: ImageFilter.blur(sigmaX: 40, sigmaY: 40),
                      child: Container(
                        margin: const EdgeInsets.symmetric(horizontal: 30),
                        padding: const EdgeInsets.all(35),
                        decoration: BoxDecoration(
                          color: Colors.white.withOpacity(0.04),
                          borderRadius: BorderRadius.circular(28),
                          border: Border.all(color: Colors.white.withOpacity(0.22), width: 1.5),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.4),
                              blurRadius: 30,
                              offset: const Offset(0, 10),
                            )
                          ],
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const ProgressRing(
                              activeColor: Color(0xFF00FF87),
                              backgroundColor: Colors.white10,
                              strokeWidth: 4.5,
                            ),
                            const SizedBox(height: 30),
                            const Text(
                              'NativeLoopTimer',
                              style: TextStyle(
                                fontSize: 22, 
                                fontWeight: FontWeight.w900, 
                                color: Colors.white,
                                letterSpacing: -0.6,
                              ),
                            ),
                            const SizedBox(height: 12),
                            Text(
                              '已成功进入“极致轻量化挂机”模式。\n\n前端渲染引擎已完全销毁释放，Python 高精度内核将持续守护您的专注计划。',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                fontSize: 13, 
                                color: Colors.white.withOpacity(0.65), 
                                height: 1.6,
                              ),
                            )
                          ],
                        ),
                      ),
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

/// 🌊 CustomPainter to draw a beautiful, animated liquid sine wave inside the countdown sphere
class LiquidWavePainter extends CustomPainter {
  final double percent;
  final double wavePhase;
  final Color colorStart;
  final Color colorEnd;

  LiquidWavePainter({
    required this.percent,
    required this.wavePhase,
    required this.colorStart,
    required this.colorEnd,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // Wave height calculated from remaining time percent (1.0 is full, 0.0 is empty)
    final double liquidHeight = size.height * (1.0 - percent);
    
    // Create circular path clipping boundaries
    final Path circlePath = Path()
      ..addOval(Rect.fromLTWH(0, 0, size.width, size.height));
    canvas.clipPath(circlePath);

    // Primary wave (Sine Wave)
    final paint1 = Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomCenter,
        end: Alignment.topCenter,
        colors: [
          colorStart,
          colorEnd,
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height))
      ..style = PaintingStyle.fill;

    final path1 = Path();
    path1.moveTo(0, size.height);
    for (double x = 0; x <= size.width; x++) {
      // y = Amplitude * sin(frequency * x + phase) + verticalShift
      final double y = 7.0 * math.sin((x / size.width * 2 * math.pi) + wavePhase) + liquidHeight;
      path1.lineTo(x, y);
    }
    path1.lineTo(size.width, size.height);
    path1.lineTo(0, size.height);
    path1.close();
    canvas.drawPath(path1, paint1);

    // Secondary wave (Cosine Wave - phase shifted, lower opacity for depth)
    final paint2 = Paint()
      ..shader = LinearGradient(
        begin: Alignment.bottomCenter,
        end: Alignment.topCenter,
        colors: [
          colorStart.withOpacity(0.55),
          colorEnd.withOpacity(0.25),
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height))
      ..style = PaintingStyle.fill;

    final path2 = Path();
    path2.moveTo(0, size.height);
    for (double x = 0; x <= size.width; x++) {
      final double y = 5.0 * math.cos((x / size.width * 2 * math.pi) - wavePhase + math.pi / 3) + liquidHeight + 3.0;
      path2.lineTo(x, y);
    }
    path2.lineTo(size.width, size.height);
    path2.lineTo(0, size.height);
    path2.close();
    canvas.drawPath(path2, paint2);
  }

  @override
  bool shouldRepaint(covariant LiquidWavePainter oldDelegate) {
    return oldDelegate.percent != percent ||
        oldDelegate.wavePhase != wavePhase ||
        oldDelegate.colorStart != colorStart ||
        oldDelegate.colorEnd != colorEnd;
  }
}

/// 💎 Bespoke premium Apple Aqua 3D Gel Capsule Button
class AquaGelButton extends StatelessWidget {
  final String label;
  final Color baseColor;
  final Color shadowColor;
  final VoidCallback? onPressed;
  final String? icon;

  const AquaGelButton({
    Key? key,
    required this.label,
    required this.baseColor,
    required this.shadowColor,
    this.onPressed,
    this.icon,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final bool isEnabled = onPressed != null;

    return MouseRegion(
      cursor: isEnabled ? SystemMouseCursors.click : SystemMouseCursors.forbidden,
      child: GestureDetector(
        onTap: onPressed,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          height: 48,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(100),
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: isEnabled 
                ? [
                    baseColor.withRed((baseColor.red + 40).clamp(0, 255)).withGreen((baseColor.green + 40).clamp(0, 255)).withBlue((baseColor.blue + 40).clamp(0, 255)), // Bright upper highlight
                    baseColor, // Core body
                  ]
                : [
                    Colors.white.withOpacity(0.08),
                    Colors.white.withOpacity(0.02),
                  ],
            ),
            boxShadow: isEnabled
                ? [
                    BoxShadow(
                      color: shadowColor.withOpacity(0.35),
                      blurRadius: 12,
                      offset: const Offset(0, 4),
                    ),
                    BoxShadow(
                      color: Colors.white.withOpacity(0.20),
                      blurRadius: 1,
                      spreadRadius: -1,
                      offset: const Offset(0, 1),
                    )
                  ]
                : [],
            border: Border.all(
              color: isEnabled 
                ? Colors.white.withOpacity(0.25)
                : Colors.white.withOpacity(0.05), 
              width: 1.0,
            ),
          ),
          child: Stack(
            children: [
              // 3D Specular highlight crescent reflection (Upper 40% of capsule)
              if (isEnabled)
                Positioned(
                  top: 1.5,
                  left: 6,
                  right: 6,
                  child: Container(
                    height: 19,
                    decoration: BoxDecoration(
                      borderRadius: const BorderRadius.vertical(top: Radius.circular(100)),
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          Colors.white.withOpacity(0.42),
                          Colors.white.withOpacity(0.0),
                        ],
                      ),
                    ),
                  ),
                ),
              // Label and icon text row
              Center(
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    if (icon != null) ...[
                      Text(
                        icon!, 
                        style: TextStyle(
                          fontSize: 14, 
                          color: isEnabled ? Colors.white : Colors.white.withOpacity(0.3),
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                    Text(
                      label,
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w800,
                        color: isEnabled ? Colors.white : Colors.white.withOpacity(0.3),
                        letterSpacing: -0.2,
                        shadows: isEnabled ? [
                          Shadow(
                            color: Colors.black.withOpacity(0.35),
                            offset: const Offset(0, 1.2),
                            blurRadius: 2.0,
                          )
                        ] : [],
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

extension on String {
  String strip() => trim();
}
