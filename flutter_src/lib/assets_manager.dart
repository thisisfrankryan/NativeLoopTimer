import 'dart:io';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

class BackendLaunchCommand {
  final String executable;
  final List<String> arguments;

  const BackendLaunchCommand(this.executable, this.arguments);
}

class AssetsManager {
  /// In development, prefer the repository backend.py so Flutter can talk to the
  /// current IPC protocol without rebuilding backend.exe on every source edit.
  /// In packaged builds, extract and launch the bundled backend.exe asset.
  static Future<BackendLaunchCommand> resolveBackendLaunch() async {
    final sourceBackend = _findSourceBackend();
    if (sourceBackend != null) {
      return BackendLaunchCommand(_pythonExecutable(), [sourceBackend]);
    }

    final exePath = await extractBackend();
    return BackendLaunchCommand(exePath, const []);
  }

  static String? _findSourceBackend() {
    final candidates = <String>[
      p.normalize(p.join(Directory.current.path, '..', 'backend.py')),
      p.normalize(p.join(Directory.current.path, 'backend.py')),
      p.normalize(p.join(File(Platform.resolvedExecutable).parent.path, '..', 'backend.py')),
    ];

    for (final candidate in candidates) {
      if (File(candidate).existsSync()) {
        return candidate;
      }
    }
    return null;
  }

  static String _pythonExecutable() {
    final envPython = Platform.environment['PYTHON'];
    if (envPython != null && envPython.trim().isNotEmpty) {
      return envPython;
    }
    return Platform.isWindows ? 'python' : 'python3';
  }

  static Future<String> extractBackend() async {
    final directory = await getApplicationSupportDirectory();
    final exePath = p.join(directory.path, 'backend.exe');
    final file = File(exePath);

    await file.parent.create(recursive: true);

    final byteData = await rootBundle.load('assets/backend.exe');
    final bytes = byteData.buffer.asUint8List(byteData.offsetInBytes, byteData.lengthInBytes);
    var shouldWrite = true;
    if (await file.exists()) {
      final existing = await file.readAsBytes();
      shouldWrite = existing.length != bytes.length;
      if (!shouldWrite) {
        for (var i = 0; i < bytes.length; i++) {
          if (existing[i] != bytes[i]) {
            shouldWrite = true;
            break;
          }
        }
      }
    }

    if (shouldWrite) {
      await file.writeAsBytes(bytes, flush: true);
    }

    if (!await file.exists()) {
      throw OSError('Failed to extract backend.exe asset to $exePath');
    }

    return exePath;
  }
}
