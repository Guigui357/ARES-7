# ARES-7 FAST / LOCAL

Assistente de voz 100% local para Ubuntu 24.04, feito para rodar em notebook
fraco (4 GB de RAM, sem GPU). Pipeline:

```
Microfone → arecord (ALSA) → VAD → whisper.cpp → texto
          → roteador de intenções → (comando local) ou Qwen via llama.cpp
          → resposta → Piper → alto-falante
```

Sem nuvem, sem APIs externas, sem chaves.

## Uso

```bash
python3 ares.py              # GUI (Tkinter)
python3 ares.py --cli        # terminal
python3 ares.py --diagnose   # relatorio de saude do sistema
python3 ares.py --benchmark  # mede desempenho
python3 ares.py --low-memory # modo ULTRA FAST
python3 ares.py --remote     # ativa o servidor remoto (celular via navegador)
python3 ares.py --wake       # wake word "ares" (modo CONTINUOUS)
python3 ares.py --debug      # logs detalhados
```

## Configuração

Edite `config.json` (nunca o código-fonte). Campos principais:

- `whisper.binary` / `whisper.model` — caminhos (vazio = auto-detectar)
- `llm.host` / `llm.port` — servidor llama.cpp (padrão 127.0.0.1:8080)
- `llm.server_bin` / `llm.server_model` — para auto-start do servidor
- `audio.input` — `"auto"`, índice, nome parcial ou `plughw:X,Y`
- `tts.model` — voz Piper `.onnx` (vazio = auto-detectar em `./models`)
- `memory.max_tokens_budget` — teto de tokens do prompt (cura o erro de contexto)
- `remote.token` — troque antes de expor na LAN

Variáveis de ambiente também funcionam: `ARES7_WHISPER_MODEL`,
`ARES7_PIPER_MODEL`, `ARES7_LLM_HOST`, `ARES7_LOW_MEMORY` etc.

## Modelos

Coloque em `./models` (ou aponte no config):

- Whisper: `ggml-tiny.bin` ou `ggml-base.bin` (whisper.cpp)
- Qwen: `qwen2.5-1.5b-instruct-q4_k_m.gguf` (llama.cpp, `llama serve`)
- Piper: voz pt_BR `.onnx` + `.onnx.json`


## Funções locais

O ARES-7 já possui comandos locais para:

- 🎤 voz com VAD + Whisper.cpp
- 🧠 Qwen via llama.cpp, sem nuvem
- 🔊 Piper/fallback de voz
- 📝 notas e memória persistente SQLite
- ⏱️ timers e lembretes
- 🧮 calculadora segura
- 📸 screenshot
- 🔊 volume/mudo e brilho
- 🔒 bloquear, suspender, reiniciar e desligar com confirmação
- 📂 abrir/listar/buscar arquivos e pastas
- 🌐 abrir sites, pesquisar e abrir URLs diretamente
- 🎵 controlar mídia via playerctl
- 🖥️ abrir/fechar aplicativos
- 📊 CPU, RAM, temperatura, bateria, disco, IP e uptime
- 📱 controle remoto HTTP com token
- 🧹 limpar o contexto do chat pela GUI, CLI ou interface web

## Estrutura

```
ares.py             launcher (GUI/CLI/diagnose/benchmark)
core/              assistant, router, context, memory, config, logs
audio/             devices, recorder, vad, player
stt/               whisper.cpp
llm/               llama.cpp (endpoints auto-detectados, autostart, reconnect)
tts/               piper (+ fallback espeak-ng)
tools/             system, files, apps, media, network
remote/            servidor HTTP com token
gui/               HUD Tkinter (TEST MICROPHONE, RECONNECT, INPUT DEVICES)
web/               interface remota para celular
diagnose.py        relatório PASS/WARN/FAIL
benchmark.py       tempos do pipeline
setup_local_linux.sh  prepara o sistema
```

## Segurança

- Comandos perigosos (desligar, reiniciar, bloquear, fechar app, escrever
  arquivo, executar comando) pedem confirmação por voz/texto.
- O servidor remoto exige token. Não exponha na internet.
