import 'dart:io';

import 'package:llama_cpp_dart/llama_cpp_dart.dart';

/// Runs GGUF inference entirely on the device through llama.cpp.
/// The model path must point to a local .gguf file in app-private storage.
class GgufRuntime {
  GgufRuntime._(this._engine, this._chat);

  final LlamaEngine _engine;
  final EngineChat _chat;
  bool _disposed = false;

  static Future<GgufRuntime> load(String modelPath) async {
    final file = File(modelPath);
    if (!await file.exists()) {
      throw FileSystemException('Arquivo GGUF não encontrado', modelPath);
    }
    if (!modelPath.toLowerCase().endsWith('.gguf')) {
      throw ArgumentError('Selecione um arquivo .gguf válido.');
    }

    final params = ModelParams(
      path: modelPath,
      // iOS can use Metal; Android starts on CPU for broad compatibility.
      gpuLayers: Platform.isIOS ? 99 : 0,
    );
    const context = ContextParams(nCtx: 2048);

    // iOS loads symbols from the embedded llama.xcframework.
    // Android uses the package's bundled native library.
    final engine = Platform.isIOS
        ? await LlamaEngine.spawnFromProcess(
            modelParams: params,
            contextParams: context,
          )
        : await LlamaEngine.spawn(
            modelParams: params,
            contextParams: context,
          );

    try {
      final chat = await engine.createChat();
      chat.addSystem(
        'Você é o ARES-7, um assistente útil, direto e cuidadoso. '
        'Responda em português brasileiro, a menos que o usuário peça outro idioma. '
        'Não afirme ter executado ações que não executou.',
      );
      return GgufRuntime._(engine, chat);
    } catch (_) {
      await engine.dispose();
      rethrow;
    }
  }

  /// Streams response tokens from the on-device model.
  Stream<String> generate(String prompt, {int maxTokens = 192}) async* {
    if (_disposed) {
      throw StateError('O motor GGUF já foi encerrado.');
    }
    if (prompt.trim().isEmpty) return;

    await for (final event in _chat.generate(maxTokens: maxTokens)) {
      if (event is TokenEvent) {
        yield event.text;
      }
    }
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _disposed = true;
    await _engine.dispose();
  }
}
