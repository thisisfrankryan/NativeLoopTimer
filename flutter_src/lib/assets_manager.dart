import 'dart:io';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

class AssetsManager {
  /// Unpacks the bundled Python backend executable from assets to the local
  /// Application Support directory sandbox. Returns the absolute path of the executable.
  static Future<String> extractBackend() async {
    final directory = await getApplicationSupportDirectory();
    final exePath = p.join(directory.path, 'backend.exe');
    final file = File(exePath);

    // If the file already exists, we do not need to re-extract it
    if (await file.exists()) {
      return exePath;
    }

    // Ensure the parent directory exists
    await file.parent.create(recursive: true);

    // Read the binary stream of the executable from Flutter assets
    final byteData = await rootBundle.load('assets/backend.exe');
    final bytes = byteData.buffer.asUint8List(byteData.offsetInBytes, byteData.lengthInBytes);

    // Write the bytes to the application sandbox
    await file.writeAsBytes(bytes, flush: true);

    // Verify that the file exists and is executable
    if (!await file.exists()) {
      throw OSError("Failed to extract backend.exe asset to sandboxed path: $exePath");
    }

    return exePath;
  }
}
