import 'package:flutter/material.dart';

void main() {
  runApp(const AresMobileApp());
}

class AresMobileApp extends StatelessWidget {
  const AresMobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
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
}

class ChatMessage {
  const ChatMessage({required this.text, required this.isUser});
  final String text;
  final bool isUser;
}

class AresChatScreen extends StatefulWidget {
  const AresChatScreen({super.key});

  @override
  State<AresChatScreen> createState() => _AresChatScreenState();
}

class _AresChatScreenState extends State<AresChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final List<ChatMessage> _messages = <ChatMessage>[
    const ChatMessage(
      text: 'Olá! Esta é a interface móvel do ARES-7. Para conversar com a IA, configure um modelo local compatível.',
      isUser: false,
    ),
  ];

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _send() {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _messages.add(ChatMessage(text: text, isUser: true));
      _messages.add(const ChatMessage(
        text: 'Motor local ainda não configurado. Esta versão é apenas a interface; nenhuma resposta foi enviada a um servidor.',
        isUser: false,
      ));
      _controller.clear();
    });
  }

  void _showRuntimeStatus() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      backgroundColor: const Color(0xFF111A25),
      builder: (context) => const SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(24, 8, 24, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Estado dos componentes',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              SizedBox(height: 18),
              _StatusRow(label: 'Interface móvel', value: 'Disponível', ready: true),
              _StatusRow(label: 'Modelo GGUF / llama.cpp', value: 'Não integrado', ready: false),
              _StatusRow(label: 'Reconhecimento de voz offline', value: 'Não integrado', ready: false),
              _StatusRow(label: 'Voz offline (TTS)', value: 'Não integrado', ready: false),
              SizedBox(height: 12),
              Text(
                'O app ainda não executa inferência nem grava áudio. Esses motores nativos precisam ser adicionados e testados para cada plataforma.',
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
                Text('MOBILE • OFFLINE FIRST',
                    style: TextStyle(fontSize: 10, letterSpacing: 1.4)),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Estado do sistema',
            onPressed: _showRuntimeStatus,
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
              child: const Row(
                children: [
                  Icon(Icons.cloud_off, color: Color(0xFF39D6C5), size: 25),
                  SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Projetado para funcionar localmente',
                            style: TextStyle(fontWeight: FontWeight.w600)),
                        SizedBox(height: 3),
                        Text('Modelo ainda não instalado • Protótipo',
                            style: TextStyle(color: Colors.white60, fontSize: 12)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                itemCount: _messages.length,
                itemBuilder: (context, index) {
                  final message = _messages[index];
                  return Align(
                    alignment: message.isUser
                        ? Alignment.centerRight
                        : Alignment.centerLeft,
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
                      child: Text(message.text),
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
                    tooltip: 'Voz offline ainda não disponível',
                    onPressed: _showRuntimeStatus,
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
                    onPressed: _send,
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
  Widget build(BuildContext context) {
    return Padding(
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
          Text(value, style: const TextStyle(color: Colors.white60, fontSize: 12)),
        ],
      ),
    );
  }
}
