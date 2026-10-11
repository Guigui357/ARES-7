import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'gguf_runtime.dart';

void main() => runApp(const AresMobileApp());

class AresMobileApp extends StatelessWidget {
  const AresMobileApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'ARES-7',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF39D6C5),
            brightness: Brightness.dark,
          ),
          scaffoldBackgroundColor: const Color(0xFF080D14),
          useMaterial3: true,
        ),
        home: const AresChatScreen(),
      );
}

class ChatMessage {
  ChatMessage({required this.text, required this.isUser});
  String text;
  final bool isUser;
}

class AresChatScreen extends StatefulWidget {
  const AresChatScreen({super.key});

  @override
  State<AresChatScreen> createState() => _AresChatScreenState();
}

class _AresChatScreenState extends State<AresChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<ChatMessage> _messages = [
    ChatMessage(
      text: 'ARES-7 Mobile. Importe um modelo GGUF para iniciar a IA local.',
      isUser: false,
    ),
  ];

  GgufRuntime? _runtime;
  String? _modelName;
  bool _loadingModel = false;
  bool _generating = false;
  String? _error;

  bool get _ready => _runtime != null;

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    _runtime?.dispose();
    super.dispose();
  }

  Future<void> _pickAndLoadModel() async {
    if (_loadingModel || _generating) return;
    setState(() {
      _loadingModel = true;
      _error = null;
    });

    GgufRuntime? candidate;
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['gguf'],
        allowMultiple: false,
        withData: false,
      );
      if (result == null || result.files.isEmpty) return;

      final picked = result.files.single;
      final sourcePath = picked.path;
      if (sourcePath == null) {
        throw Exception('Não foi possível acessar o caminho do arquivo selecionado.');
      }

      final safeName = picked.name.replaceAll(RegExp(r'[^a-zA-Z0-9._-]'), '_');

      // Prefer copying the model into app storage, but don't make loading
      // depend on path_provider returning a documents directory. Some Android
      // devices/file-picker providers can fail to resolve that path; the
      // selected file path is still usable for the current import session.
      var modelPath = sourcePath;
      try {
        final documents = await getApplicationDocumentsDirectory();
        final modelDirectory = Directory('${documents.path}/ares_models');
        await modelDirectory.create(recursive: true);
        final destination = File('${modelDirectory.path}/$safeName');
        if (File(sourcePath).absolute.path != destination.absolute.path) {
          await File(sourcePath).copy(destination.path);
        }
        modelPath = destination.path;
      } catch (_) {
        // Fall back to the path provided by FilePicker.
      }

      // Release the previous model before loading another one to avoid
      // temporarily holding two large GGUF models in RAM.
      final old = _runtime;
      if (old != null) {
        setState(() {
          _runtime = null;
          _modelName = null;
        });
        await old.dispose();
      }

      candidate = await GgufRuntime.load(modelPath);
      if (!mounted) {
        await candidate.dispose();
        return;
      }
      setState(() {
        _runtime = candidate;
        _modelName = safeName;
        _messages.add(ChatMessage(
          text: 'Modelo $safeName carregado. As mensagens agora são processadas no dispositivo.',
          isUser: false,
        ));
      });
    } catch (e) {
      await candidate?.dispose();
      if (mounted) setState(() => _error = 'Falha ao carregar o GGUF: $e');
    } finally {
      if (mounted) setState(() => _loadingModel = false);
    }
  }

  Future<void> _send() async {
    final prompt = _controller.text.trim();
    if (prompt.isEmpty || _generating) return;
    if (_runtime == null) {
      setState(() => _error = 'Importe um modelo GGUF antes de enviar mensagens.');
      return;
    }

    _controller.clear();
    final answer = ChatMessage(text: '', isUser: false);
    setState(() {
      _error = null;
      _generating = true;
      _messages
        ..add(ChatMessage(text: prompt, isUser: true))
        ..add(answer);
    });
    _scrollToBottom();

    try {
      await for (final token in _runtime!.generate(prompt, maxTokens: 192)) {
        if (!mounted) return;
        setState(() => answer.text += token);
        _scrollToBottom();
      }
      if (mounted && answer.text.trim().isEmpty) {
        setState(() => answer.text = '(O modelo não gerou texto.)');
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          answer.text = 'Erro durante a inferência local.';
          _error = '$e';
        });
      }
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _showStatus() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      backgroundColor: const Color(0xFF111A25),
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Estado dos componentes',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 18),
              const _StatusRow(label: 'Interface móvel', value: 'Disponível', ready: true),
              _StatusRow(
                label: 'Motor GGUF / llama.cpp',
                value: _ready ? 'Carregado' : 'Aguardando modelo',
                ready: _ready,
              ),
              _StatusRow(label: 'Modelo', value: _modelName ?? 'Nenhum', ready: _ready),
              const _StatusRow(
                label: 'Reconhecimento de voz offline',
                value: 'Pendente',
                ready: false,
              ),
              const _StatusRow(
                label: 'Voz offline (TTS)',
                value: 'Pendente',
                ready: false,
              ),
              const SizedBox(height: 12),
              const Text(
                'A inferência GGUF ocorre localmente. O reconhecimento e a síntese de voz ainda não foram integrados.',
                style: TextStyle(color: Colors.white70),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Row(
          children: [
            Icon(Icons.memory, color: Color(0xFF39D6C5)),
            SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('ARES-7', style: TextStyle(fontWeight: FontWeight.w800)),
                Text('MOBILE • INFERÊNCIA LOCAL',
                    style: TextStyle(fontSize: 10, letterSpacing: 1.4)),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Importar modelo GGUF',
            onPressed: _loadingModel || _generating ? null : _pickAndLoadModel,
            icon: _loadingModel
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.folder_open),
          ),
          IconButton(
            tooltip: 'Estado do sistema',
            onPressed: _showStatus,
            icon: const Icon(Icons.info_outline),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Container(
              margin: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF111A25),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: const Color(0xFF263747)),
              ),
              child: Row(
                children: [
                  Icon(_ready ? Icons.memory : Icons.cloud_off,
                      color: const Color(0xFF39D6C5), size: 25),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(_ready ? 'IA local pronta' : 'Sem servidor ou API paga',
                            style: const TextStyle(fontWeight: FontWeight.w600)),
                        const SizedBox(height: 3),
                        Text(
                          _modelName ?? 'Toque na pasta para importar um arquivo .gguf',
                          style: const TextStyle(color: Colors.white60, fontSize: 12),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  TextButton(
                    onPressed: _loadingModel || _generating ? null : _pickAndLoadModel,
                    child: const Text('Modelo'),
                  ),
                ],
              ),
            ),
            if (_error != null)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF4A2025),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(_error!, style: const TextStyle(color: Colors.white)),
              ),
            Expanded(
              child: ListView.builder(
                controller: _scrollController,
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                itemCount: _messages.length,
                itemBuilder: (context, index) {
                  final message = _messages[index];
                  return Align(
                    alignment: message.isUser ? Alignment.centerRight : Alignment.centerLeft,
                    child: Container(
                      constraints: BoxConstraints(
                        maxWidth: MediaQuery.sizeOf(context).width * 0.84,
                      ),
                      margin: const EdgeInsets.symmetric(vertical: 6),
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: message.isUser
                            ? const Color(0xFF124B4B)
                            : const Color(0xFF151F2B),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Text(message.text.isEmpty && _generating
                          ? 'Gerando resposta…'
                          : message.text),
                    ),
                  );
                },
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
              child: Row(
                children: [
                  IconButton.filledTonal(
                    tooltip: 'Voz offline ainda não integrada',
                    onPressed: _showStatus,
                    icon: const Icon(Icons.mic_none),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      minLines: 1,
                      maxLines: 5,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                      decoration: InputDecoration(
                        hintText: 'Mensagem para o ARES-7...',
                        filled: true,
                        fillColor: const Color(0xFF111A25),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(22),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 12,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    onPressed: _generating ? null : _send,
                    icon: const Icon(Icons.arrow_upward),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
    required this.label,
    required this.value,
    required this.ready,
  });

  final String label;
  final String value;
  final bool ready;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 7),
        child: Row(
          children: [
            Icon(
              ready ? Icons.check_circle_outline : Icons.pending_outlined,
              color: ready ? const Color(0xFF39D6C5) : Colors.orangeAccent,
              size: 20,
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(label)),
            Flexible(
              child: Text(
                value,
                textAlign: TextAlign.end,
                style: const TextStyle(color: Colors.white60, fontSize: 12),
              ),
            ),
          ],
        ),
      );
}
