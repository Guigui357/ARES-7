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
python3 ares.py --autonomous "verifique o sistema"   # IA autonoma (uma mensagem)
```

## IA Autonoma

O ARES-7 detecta o que voce quer fazer, valida se da certo e faz — em zero
rodadas ou uma mensagem. Isso vale para **todas** as interfaces: voz, CLI,
GUI, web remota e WhatsApp.

Fluxo:

```
requisicao -> detecta intencao -> valida pre-requisitos -> executa -> resultado
```

- **Detecta**: regras locais primeiro (nunca acordam o LLM); se o pedido for
  mais complexo, o Qwen planeja os passos em uma unica chamada.
- **Valida**: antes de cada passo o motor confere parametros, semantica e
  dependencias externas (ex.: `wpctl`, `brightnessctl`, `playerctl`). Se algo
  nao esta instalado, o erro diz o que falta em vez de falhar calado.
- **Executa**: as acaoes rodam em sequencia e o resultado volta pronto.

Acoes de risco (desligar, reiniciar, suspender, bloquear tela, fechar app)
pedem confirmacao — uma unica mensagem ("sim"/"nao"), nada mais.

```bash
python3 ares.py --autonomous "verifique o sistema"
python3 ares.py --autonomous "anote comprar pao"
python3 ares.py --autonomous "quanto eh 15 por cento de 200"
python3 ares.py --autonomous "abra o navegador"
python3 ares.py --autonomous "desligar o computador"   # pede confirmacao
python3 ares.py --autonomous "sim"                     # confirma
```

Configuracao em `config.json`, secao `autonomous`:

```json
"autonomous": {
  "enabled": true,
  "confirm_required": true,
  "max_steps": 10,
  "llm_planning": true,
  "fallback_to_heuristic": true
}
```

Variaveis de ambiente: `ARES7_AUTONOMOUS_ENABLED`,
`ARES7_AUTONOMOUS_STEPS`, `ARES7_AUTONOMOUS_PLANNING`,
`ARES7_AUTONOMOUS_CONFIRM`.

## Modo daemon (sem mensagem nenhuma)

O daemon nao espera requisicao: ele roda, observa a maquina, decide o que
fazer e age sozinho. So fala quando ha algo que vale a pena dizer.

```bash
python3 ares.py --daemon         # roda sozinho, Ctrl+C para parar
python3 ares.py --daemon-once    # um ciclo e sai (util para cron)
```

O ciclo e: **observa → decide → executa → registra**.

- **Observa** — RAM, disco, bateria, temperatura, CPU, servidor do Qwen e
  acoes pendentes de confirmacao.
- **Decide** — o Qwen avalia a situacao e devolve o que fazer; sem LLM, valem
  as regras locais.
- **Executa** — acoes seguras rodam sozinhas (limpar o contexto, reconectar o
  llama.cpp, avisar). Acoes de risco ficam na fila para voce confirmar.
- **Registra** — tudo em `~/.ares/daemon.log`.

So repete o que e novo: uma condicao ja reportada nao vira spam, e o
`report_cooldown` segura acoes repetidas.

Configuracao em `config.json`, secao `daemon`:

```json
"daemon": {
  "enabled": false,
  "interval": 60,
  "report_cooldown": 900,
  "auto_actions": true,
  "llm_decisions": true,
  "log": true,
  "verbose": false
}
```

Variaveis: `ARES7_DAEMON_ENABLED`, `ARES7_DAEMON_INTERVAL`,
`ARES7_DAEMON_COOLDOWN`, `ARES7_DAEMON_ACTIONS`, `ARES7_DAEMON_DECISIONS`.

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


## PyInstaller

O ARES-7 pode ser empacotado como aplicativo Linux sem instalar bibliotecas Python extras do projeto:

```bash
./build_pyinstaller.sh
```

O executável será criado em `dist/ARES-7/ARES-7`.

O build inclui o código Python, `config.json` inicial e a interface web. Um `config.json` colocado ao lado do executável tem prioridade e pode ser editado normalmente.

**Importante:** PyInstaller não substitui os componentes externos. `whisper-cli`, servidor `llama`/llama.cpp, modelos GGUF/Whisper e Piper continuam separados, mantendo o ARES-7 leve para máquinas com 4 GB de RAM.

Teste após o build:

```bash
./dist/ARES-7/ARES-7 --version
./dist/ARES-7/ARES-7 --status
./dist/ARES-7/ARES-7 --cli
```

## ARES-7 v1.2

### Usabilidade e controle
- Comandos de volume relativos: “aumente o volume em 20”.
- Mais aliases para aplicativos e suporte a Visual Studio Code/Codium.
- `--version` informa a versão instalada.
- Diagnóstico leve de Vulkan/GPU, sem carregar modelos.
- Endpoint remoto `/api/ping` para verificar rapidamente se o ARES-7 está vivo.
- Mantido o princípio: comandos locais não acordam o Qwen.

## ARES-7 v1.1

### Performance
- Fast Path local para comandos que não precisam do LLM.
- Geração curta para perguntas simples.
- Limites padrão reduzidos para máquinas com pouca RAM.
- Histórico e orçamento de contexto mais enxutos.
- Status mostra o orçamento de contexto do LLM.

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
ares.py             launcher (GUI/CLI/diagnose/benchmark/--autonomous)
core/              assistant, router, context, memory, config, logs
core/autonomous.py motor da IA autonoma (detecta, valida, executa)
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

## WhatsApp Cloud API (oficial)

O ARES-7 pode receber mensagens de texto pelo WhatsApp Business Platform e responder usando o núcleo existente (comandos locais ou Qwen/llama.cpp). A integração usa somente a biblioteca padrão do Python; fica **desativada por padrão**.

### 1. Pré-requisitos

- Uma aplicação Meta configurada com o produto WhatsApp, um número Cloud API e permissões de mensagens.
- O **Phone Number ID**, um token de acesso, o **App Secret** e um token de verificação criado por você.
- Um endpoint HTTPS público para o webhook. Em um notebook doméstico, use um reverse proxy/túnel HTTPS confiável apontando para `127.0.0.1:8766`; não exponha diretamente a porta na internet.
- O servidor ARES-7 e o serviço llama.cpp ligados quando quiser que o bot responda.

### 2. Configure sem publicar segredos

No `config.json`, preencha a seção `whatsapp`:

```json
"whatsapp": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8766,
  "verify_token": "COLOQUE_UM_SEGREDO_LONGO_AQUI",
  "app_secret": "",
  "access_token": "",
  "phone_number_id": "",
  "api_version": "v23.0",
  "allowed_senders": ["5511999999999"]
}
```

Esse bloco é um exemplo de formato, **não credenciais reais**. Substitua os valores; o número em `allowed_senders` deve conter o código do país e DDD, apenas dígitos (ex.: `55...`), sem `+`. Só remetentes listados podem acionar o ARES-7. Mantenha `allowed_senders` preenchido e não publique tokens, App Secret ou números privados no GitHub. Para segredos, prefira variáveis de ambiente:

- `ARES7_WHATSAPP_ENABLED=true`
- `ARES7_WHATSAPP_VERIFY_TOKEN`
- `ARES7_WHATSAPP_APP_SECRET`
- `ARES7_WHATSAPP_ACCESS_TOKEN`
- `ARES7_WHATSAPP_PHONE_NUMBER_ID`
- Opcional: `ARES7_WHATSAPP_HOST`, `ARES7_WHATSAPP_PORT`, `ARES7_WHATSAPP_API_VERSION`

As variáveis de ambiente têm prioridade sobre `config.json`. Não coloque os valores reais nos comandos que serão salvos no histórico do shell.

### 3. Configure o webhook na Meta

1. Inicie o ARES-7 normalmente; com `whatsapp.enabled=true`, ele inicia o listener em `127.0.0.1:8766`.
2. Configure seu proxy/túnel HTTPS para encaminhar para `http://127.0.0.1:8766/webhook`.
3. No painel Meta Developers, informe essa URL pública com o caminho `/webhook` e o mesmo `verify_token` definido acima.
4. Inscreva o app no campo de webhook `messages` do WhatsApp Business Account.
5. Envie uma mensagem de texto a partir de um número presente em `allowed_senders`.

O endpoint valida o desafio GET, verifica a assinatura POST `X-Hub-Signature-256` com o App Secret, limita o tamanho do payload e deduplica IDs recentes de mensagens. Eventos não-textuais e remetentes não autorizados são ignorados. O listener responde rapidamente à Meta e processa a mensagem em segundo plano.

### 4. Iniciar e diagnosticar

```bash
python3 ares.py --cli
```

Ou inicie a GUI como de costume. A integração permanece desligada se `whatsapp.enabled` for `false`. Se a porta estiver ocupada, escolha outra em `whatsapp.port` e ajuste o proxy.

**Limites e segurança:** o computador precisa estar ligado e acessível pelo webhook. As regras de janela de atendimento e modelos de mensagem da Meta continuam valendo; para iniciar conversas fora da janela de atendimento permitida, pode ser necessário usar um template aprovado. A integração atual processa apenas texto e não baixa mídia. Os comandos perigosos continuam sujeitos ao mecanismo de confirmação do núcleo, mas use somente números autorizados e proteja o computador e as credenciais.

## Segurança

- Comandos perigosos (desligar, reiniciar, bloquear, fechar app, escrever
  arquivo, executar comando) pedem confirmação por voz/texto.
- O servidor remoto exige token. Não exponha na internet.
