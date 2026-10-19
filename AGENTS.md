# ARES-7 - IA Autonoma

O ARES-7 agora inclui um modo **IA Autonoma** que detecta o que voce quer fazer,
valida se e possivel executar e faz, em zero rodadas ou uma mensagem.

## Como funciona

O fluxo e:

1. **Detectar** - a requisicao em linguagem natural e analisada pelo roteador de
   intencoes ou pelo LLM (Qwen via llama.cpp).
2. **Validar** - os pre-requisitos sao verificados antes da execucao
   (dependencias, permissoes, recursos disponiveis).
3. **Executar** - a ferramenta local e acionada e o resultado e reportado.

Acoes de risco (desligar, reiniciar, bloquear, etc.) exigem confirmacao do
usuario e nao sao executadas automaticamente.

## Uso

```bash
# Executa uma requisicao em modo autonomo (zero rodadas)
python3 ares.py --autonomous "verifique o sistema"

python3 ares.py --autonomous "anote comprar pao"

python3 ares.py --autonomous "quanto eh 15 por cento de 200"

python3 ares.py --autonomous "captura de tela"

python3 ares.py --autonomous "abra o navegador"
```

O modo autonomo tambem e o caminho padrao de **todas** as interfaces (voz, CLI,
GUI, web remota e WhatsApp): o nucleo `core/assistant.py` chama o motor
autonomo sempre que o roteador local nao resolve o pedido.

## Exemplos de requisicoes suportadas

| O que voce quer fazer | Exemplo |
|---|---|
| Informacoes do sistema | "verifique o sistema", "qual a temperatura?", "uso de CPU" |
| Notas | "anote comprar pao", "mostra minhas notas" |
| Calculadora | "quanto eh 2+2", "15 por cento de 200" |
| Screenshot | "captura de tela", "tire um print" |
| Volume | "aumente o volume em 20", "coloque o volume em 40%" |
| Brilho | "aumente o brilho", "diminua o brilho para 50%" |
| Abrir apps/sites | "abra o navegador", "abra o youtube" |
| Arquivos | "busque arquivo X", "liste a pasta downloads" |
| Media | "pause a musica", "proxima faixa" |
| Memoria | "lembra que meu projeto se chama X", "o que voce lembra?" |
| Timer | "timer de 5 minutos", "me lembra de beber agua em 10 minutos" |

## Como o motor decide

1. **Regras locais** (`core/router.py`) — tried primeiro e sem custo de LLM.
   Ex.: "quanto eh 2+2", "anote comprar pao", "verifique o sistema".
2. **Planejamento com LLM** (`core/autonomous.py`) — se as regras locais nao
   resolvem, o Qwen devolve em **uma unica chamada** um JSON com
   `{"actions": [...], "reply": "..."}`. As acoes sao executadas em sequencia.
3. **Validacao** — antes de cada passo o motor confere:
   - parametros obrigatorios e formato (ex.: volume `40%` ou `5%+`);
   - semantica (site conhecido, URL valida, caminho existente);
   - dependencias externas (wpctl/amixer, brightnessctl, playerctl, xdg-open);
   - nivel de risco (acoes de risco vao para confirmacao).
4. **Fallback** — se o LLM estiver offline, o motor tenta as regras locais e
   responde o que puder; nunca trava.

## Modo daemon (sem mensagem nenhuma)

O daemon nao espera requisicao nenhuma: ele roda, observa a maquina, decide o
que fazer e age sozinho. So fala quando ha algo que vale a pena dizer.

```bash
python3 ares.py --daemon         # fica rodando (Ctrl+C para parar)
python3 ares.py --daemon-once    # um ciclo de observacao e sai
```

Ciclo: **observa -> decide -> executa -> registra**.

- `core/watcher.py` observa RAM, disco, bateria, temperatura, CPU, servidor do
  Qwen e acoes pendentes de confirmacao. Cada condicao vira uma observacao
  com severidade, uma acao sugerida e o que fazer a respeito.
- `core/daemon.py` decide e executa. O Qwen avalia a situacao e devolve o que
  fazer (mesma validacao do resto do sistema); sem LLM, valem as regras locais.
- Acoes seguras rodam sozinhas: `reset_context`, `reconnect_llm`, `notify`.
- Acoes de risco nao sao executadas: ficam registradas em
  `~/.ares/autonomous_pending.json` para voce confirmar depois.
- Tudo fica em `~/.ares/daemon.log`.

O daemon so repete o que e novo: uma condicao ja reportada nao vira spam, e o
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

Variaveis de ambiente: `ARES7_DAEMON_ENABLED`, `ARES7_DAEMON_INTERVAL`,
`ARES7_DAEMON_COOLDOWN`, `ARES7_DAEMON_ACTIONS`, `ARES7_DAEMON_DECISIONS`.

## Ferramentas disponiveis

`system_info`, `process_list`, `network_info`, `volume`, `mute`, `brightness`,
`screenshot`, `media`, `list_dir`, `file_search`, `open_folder`, `open_app`,
`open_site`, `open_url`, `web_search`, `notify`, `reset_context`,
`reconnect_llm`.

Acoes de risco (exigem confirmacao): `lock_screen`, `poweroff`, `reboot`,
`suspend`, `close_app`.

## Configuracao

Edite `config.json`, secao `autonomous`:

```json
"autonomous": {
  "enabled": true,
  "confirm_required": true,
  "max_steps": 10,
  "llm_planning": true,
  "fallback_to_heuristic": true
}
```

- `enabled`: ativa o modo autonomo.
- `confirm_required`: exige confirmacao para acoes de risco.
- `max_steps`: limite de passos no plano de execucao.
- `llm_planning`: usa o LLM para planejar acoes complexas.
- `fallback_to_heuristic`: usa heuristica local quando o LLM estiver offline.

Variaveis de ambiente equivalentes: `ARES7_AUTONOMOUS_ENABLED`,
`ARES7_AUTONOMOUS_STEPS`, `ARES7_AUTONOMOUS_PLANNING`,
`ARES7_AUTONOMOUS_CONFIRM`.

## Acoes de risco (confirmacao necessaria)

Desligar, reiniciar, suspender, bloquear tela e fechar aplicativos exigem
confirmacao ("sim" ou "nao") antes da execucao. A acao pendente fica
guardada em `~/.ares/autonomous_pending.json`, entao a confirmacao funciona
tanto na mesma sessao quanto em outra invocacao do CLI:

```bash
python3 ares.py --autonomous "desligar o computador"
python3 ares.py --autonomous "sim"     # executa
python3 ares.py --autonomous "nao"     # cancela
```

## Solucao de problemas

Se o modo autonomo nao funcionar:

```bash
python3 ares.py --diagnose
```

Verifique se o servidor llama.cpp esta online (para planejamento com LLM) e se
as dependencias externas (wpctl, brightnessctl, gnome-screenshot/scrot) estao
instaladas.
