/* ARES-7 — interface móvel. Sem dependências externas. */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const chat = $('chat');
  const tokenInput = $('token');
  const feedback = $('feedback');
  const orb = $('orb');
  const panel = $('panel');
  const scrim = $('scrim');

  let token = localStorage.getItem('ares7_token') || '';
  let deferredInstall = null;
  let recognition = null;
  let connected = false;
  let polling = null;
  let failStreak = 0;

  // Token pela URL (?token=...): util para abrir um link pronto do notebook.
  // Some com ele da barra de endereco para nao ficar no historico do navegador.
  const urlToken = new URLSearchParams(location.search).get('token');
  if (urlToken) {
    token = urlToken.trim();
    localStorage.setItem('ares7_token', token);
    history.replaceState(null, '', location.pathname);
  }

  tokenInput.value = token;

  const STATE_LABEL = {
    READY: 'PRONTO', LISTENING: 'OUVINDO', PROCESSING: 'PENSANDO',
    SPEAKING: 'FALANDO', ERROR: 'ERRO', IDLE: 'AGUARDANDO',
  };
  const ORB_STATE = {
    READY: 'ready', LISTENING: 'listening', PROCESSING: 'processing',
    SPEAKING: 'speaking', ERROR: 'error',
  };

  const setFeedback = message => { feedback.textContent = message || ''; };
  const haptic = ms => { try { navigator.vibrate?.(ms); } catch (_) {} };

  // ---- markdown mínimo (seguro: escapa tudo antes) ----------------------------
  const escapeHtml = text => String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  function inline(text) {
    return text
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*\w])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }

  function renderMarkdown(raw) {
    const safe = escapeHtml(raw ?? '');
    const blocks = [];
    // Blocos de codigo sao extraidos antes para nao sofrer escape duplicado.
    let work = safe.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
      blocks.push(`<pre><code>${code}</code></pre>`);
      return `%%ARES_BLOCK_${blocks.length - 1}%%`;
    });
    work = inline(work);

    const out = [];
    let para = [];
    let list = null;
    const flushPara = () => {
      if (para.length) { out.push(`<p>${para.join('<br>')}</p>`); para = []; }
    };
    const flushList = () => {
      if (list) { out.push(`<ul>${list.map(i => `<li>${i}</li>`).join('')}</ul>`); list = null; }
    };

    for (const line of work.split('\n')) {
      const marker = line.trim().match(/^%%ARES_BLOCK_(\d+)%%$/);
      if (marker) {
        flushPara(); flushList();
        out.push(blocks[Number(marker[1])] ?? '');
        continue;
      }
      const item = line.match(/^\s*[-•*]\s+(.*)$/);
      if (item) {
        flushPara();
        (list = list || []).push(item[1]);
        continue;
      }
      if (!line.trim()) { flushPara(); flushList(); continue; }
      flushList();
      para.push(line);
    }
    flushPara();
    flushList();
    return out.join('');
  }

  // ---- mensagens ----------------------------------------------------------------
  function add(who, text, options = {}) {
    const welcome = chat.querySelector('.welcome');
    if (welcome) welcome.remove();
    const item = document.createElement('article');
    const mine = who === 'USER';
    item.className = 'msg ' + (mine ? 'user' : 'ares');

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = mine ? 'EU' : 'A7';

    const col = document.createElement('div');
    col.className = 'msg-col';

    const head = document.createElement('div');
    head.className = 'msg-head';
    const name = document.createElement('span');
    name.textContent = mine ? 'VOCÊ' : 'ARES-7';
    const time = document.createElement('span');
    time.textContent = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    head.append(name, time);

    if (!mine && options.copy !== false) {
      const copy = document.createElement('button');
      copy.className = 'msg-copy';
      copy.type = 'button';
      copy.textContent = 'COPIAR';
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(String(text));
          copy.textContent = 'OK';
        } catch (_) { copy.textContent = 'FALHOU'; }
        setTimeout(() => { copy.textContent = 'COPIAR'; }, 1400);
      });
      head.appendChild(copy);
    }

    const body = document.createElement('div');
    body.className = 'msg-body';
    body.innerHTML = renderMarkdown(text);

    col.append(head, body);
    item.append(avatar, col);
    chat.appendChild(item);
    chat.scrollTop = chat.scrollHeight;
  }

  function showTyping() {
    const welcome = chat.querySelector('.welcome');
    if (welcome) welcome.remove();
    const item = document.createElement('article');
    item.className = 'msg ares';
    item.id = 'typing';
    item.innerHTML = '<div class="msg-avatar">A7</div><div class="msg-col">'
      + '<div class="msg-body"><span class="typing"><i></i><i></i><i></i></span></div></div>';
    chat.appendChild(item);
    chat.scrollTop = chat.scrollHeight;
  }
  const hideTyping = () => { document.getElementById('typing')?.remove(); };

  // ---- API ----------------------------------------------------------------------
  async function api(path, method = 'GET', payload) {
    const opts = { method, headers: { 'X-Ares7-Token': token } };
    if (payload !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(payload);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      setConnected(false);
      setFeedback('Token inválido. Confira e toque em Conectar.');
      throw new Error('Token inválido');
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Erro HTTP ${res.status}`);
    return data;
  }

  // ---- conexão ------------------------------------------------------------------
  function setConnected(value) {
    connected = value;
    orb.dataset.state = value ? 'ready' : 'idle';
    $('brand-sub').textContent = value ? 'ASSISTENTE LOCAL' : 'DESCONECTADO';
    $('connect-card').style.display = value ? 'none' : '';
    if (value) startPolling();
    else stopPolling();
  }

  async function connect() {
    token = tokenInput.value.trim();
    if (!token) { setFeedback('Digite o token configurado no notebook.'); return; }
    localStorage.setItem('ares7_token', token);
    setFeedback('Conectando…');
    try {
      await api('/api/ping');
      setConnected(true);
      setFeedback('');
      await refresh();
      haptic(12);
    } catch (err) {
      setConnected(false);
      setFeedback(err.message || 'Não foi possível conectar. Confira Wi-Fi, endereço e token.');
    }
  }

  $('save-token').addEventListener('click', connect);
  tokenInput.addEventListener('keydown', e => { if (e.key === 'Enter') connect(); });

  // ---- envio --------------------------------------------------------------------
  async function send(text) {
    const input = $('text');
    const message = (text ?? input.value).trim();
    if (!message) return;
    input.value = '';
    add('USER', message);
    orb.dataset.state = 'processing';
    $('send').disabled = true;
    showTyping();
    try {
      const data = await api('/api/chat', 'POST', { text: message });
      hideTyping();
      add('ARES-7', data.reply || '(sem resposta de texto)');
      setFeedback('');
      haptic(8);
    } catch (err) {
      hideTyping();
      add('ARES-7', `Não consegui concluir: ${err.message}`);
    } finally {
      $('send').disabled = false;
      refresh();
    }
  }

  $('send').addEventListener('click', () => send());
  $('text').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => send(chip.dataset.send));
  });

  $('clear').addEventListener('click', async () => {
    try {
      await api('/api/clear', 'POST', {});
      chat.textContent = '';
      add('ARES-7', 'Contexto da conversa limpo. A memória permanente não foi apagada.');
    } catch (err) { setFeedback(err.message); }
  });

  // ---- microfones ----------------------------------------------------------------
  const micBtn = $('mic');
  const micReset = () => {
    micBtn.classList.remove('is-listening');
    micBtn.querySelector('.mic-label').textContent = 'MICROFONE DO NOTEBOOK';
  };
  micBtn.addEventListener('click', async () => {
    try {
      if (micBtn.classList.contains('is-listening')) {
        await api('/api/stop', 'POST', {});
        micReset();
        orb.dataset.state = 'ready';
      } else {
        const data = await api('/api/listen', 'POST', {});
        if (data.started) {
          micBtn.classList.add('is-listening');
          micBtn.querySelector('.mic-label').textContent = 'PARAR';
          orb.dataset.state = 'listening';
          setFeedback('O notebook está ouvindo. Para usar o microfone do celular, use “Ditar”.');
          haptic(14);
        } else {
          setFeedback('O ARES-7 não conseguiu iniciar a escuta. Confira o estado no notebook.');
        }
      }
    } catch (err) { setFeedback(err.message); micReset(); }
  });

  const dictateBtn = $('dictate');
  const dictateReset = () => {
    dictateBtn.classList.remove('is-listening');
    dictateBtn.querySelector('.mic-label').textContent = 'DITAR';
  };
  dictateBtn.addEventListener('click', () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setFeedback('Este navegador não tem ditado por voz. Use o teclado do celular ou o microfone do notebook.');
      return;
    }
    if (recognition) { recognition.stop(); return; }
    recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    dictateBtn.classList.add('is-listening');
    dictateBtn.querySelector('.mic-label').textContent = 'OUVINDO';
    orb.dataset.state = 'listening';
    setFeedback('Fale agora.');
    recognition.onresult = event => {
      $('text').value = event.results[0][0].transcript;
      setFeedback('Texto reconhecido. Revise e toque em Enviar.');
      $('text').focus();
    };
    recognition.onerror = event => setFeedback(`Falha no ditado: ${event.error}.`);
    recognition.onend = () => { recognition = null; dictateReset(); if (connected) orb.dataset.state = 'ready'; };
    try { recognition.start(); } catch (err) { setFeedback(err.message); recognition = null; dictateReset(); }
  });

  // ---- status --------------------------------------------------------------------
  function setPill(id, ok, text) {
    const el = $(id);
    el.className = 'pill ' + (ok ? 'ok' : 'bad');
    el.innerHTML = `${text.split(' ')[0]} <b>${ok ? 'OK' : 'OFF'}</b>`;
  }

  async function refresh() {
    if (!token || !connected) return;
    try {
      const s = await api('/api/status');
      failStreak = 0;
      const state = s.state || 'READY';
      if (!micBtn.classList.contains('is-listening') && !recognition) {
        orb.dataset.state = ORB_STATE[state] || 'ready';
      }
      const cpu = s.cpu != null ? Math.round(s.cpu) : null;
      $('st-cpu').textContent = cpu != null ? `${cpu}%` : '--';
      $('bar-cpu').style.width = `${cpu != null ? Math.min(100, cpu) : 0}%`;
      const ramPct = s.ram_total_gb ? (s.ram_used_gb / s.ram_total_gb) * 100 : null;
      $('st-ram').textContent = s.ram_total_gb ? `${s.ram_used_gb}/${s.ram_total_gb} GB` : '--';
      const ramBar = $('bar-ram');
      ramBar.style.width = `${ramPct != null ? Math.min(100, ramPct) : 0}%`;
      ramBar.classList.toggle('warn', ramPct != null && ramPct > 88);
      setPill('st-whisper', s.whisper, 'WHISPER');
      setPill('st-qwen', s.llm, 'QWEN');
      setPill('st-piper', s.piper, 'PIPER');
      $('sys-extra').textContent = [s.llm_model, s.mic, s.temp != null ? `${s.temp}°C` : null]
        .filter(Boolean).join(' · ') || 'Sem detalhes extras.';
      if (state === 'READY' && micBtn.classList.contains('is-listening')) micReset();
    } catch (_) {
      // Falhou: nao spamma o feedback a cada 5 s, so depois de varias tentativas.
      failStreak += 1;
      if (failStreak >= 3) {
        setConnected(false);
        setFeedback('Conexão perdida. Toque em Conectar para reconectar.');
      }
    }
  }

  function startPolling() {
    stopPolling();
    polling = window.setInterval(refresh, 5000);
  }
  function stopPolling() {
    if (polling) { window.clearInterval(polling); polling = null; }
  }

  // ---- painel --------------------------------------------------------------------
  function openPanel(open) {
    panel.classList.toggle('is-open', open);
    panel.setAttribute('aria-hidden', String(!open));
    $('panel-toggle').setAttribute('aria-expanded', String(open));
    scrim.hidden = !open;
    if (open) loadPanel();
  }
  $('panel-toggle').addEventListener('click', () => openPanel(true));
  $('panel-close').addEventListener('click', () => openPanel(false));
  scrim.addEventListener('click', () => openPanel(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') openPanel(false); });

  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('is-active', t === tab);
        t.setAttribute('aria-selected', String(t === tab));
      });
      document.querySelectorAll('.tab-pane').forEach(p => {
        p.classList.toggle('is-active', p.dataset.pane === tab.dataset.tab);
      });
      loadPanel();
    });
  });

  async function loadPanel() {
    const active = document.querySelector('.tab.is-active')?.dataset.tab;
    if (active === 'notas') return loadNotes();
    if (active === 'memoria') return loadMemory();
    if (active === 'daemon') return loadDaemon();
  }

  async function loadNotes() {
    const list = $('notes-list');
    try {
      const data = await api('/api/notes');
      list.innerHTML = '';
      if (!data.notes?.length) {
        list.innerHTML = '<li class="empty">Nenhuma nota ainda.</li>';
        return;
      }
      data.notes.forEach(note => {
        const li = document.createElement('li');
        li.textContent = note;
        list.appendChild(li);
      });
    } catch (err) { list.innerHTML = `<li class="empty">${err.message}</li>`; }
  }

  async function loadMemory() {
    const list = $('memory-list');
    try {
      const data = await api('/api/memory');
      list.innerHTML = '';
      if (!data.facts?.length) {
        list.innerHTML = '<li class="empty">A memória está vazia.</li>';
        return;
      }
      data.facts.forEach(fact => {
        const li = document.createElement('li');
        li.textContent = fact.content;
        list.appendChild(li);
      });
    } catch (err) { list.innerHTML = `<li class="empty">${err.message}</li>`; }
  }

  async function loadDaemon() {
    const log = $('daemon-log');
    try {
      const data = await api('/api/daemon');
      const pending = $('daemon-pending');
      if (data.pending) {
        pending.hidden = false;
        $('daemon-pending-text').textContent = data.pending.question || 'Ação aguardando confirmação.';
      } else {
        pending.hidden = true;
      }
      $('daemon-config').textContent = data.enabled
        ? `Daemon ativo, a cada ${data.interval}s.`
        : 'Daemon desligado. Ative com: python3 ares.py --daemon';
      log.innerHTML = '';
      if (!data.log?.length) {
        log.innerHTML = '<li class="empty">Sem registros ainda.</li>';
        return;
      }
      data.log.forEach(line => {
        const li = document.createElement('li');
        li.textContent = line;
        log.appendChild(li);
      });
    } catch (err) { log.innerHTML = `<li class="empty">${err.message}</li>`; }
  }

  // ---- instalacao e service worker -------------------------------------------------
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredInstall = event;
    $('install').hidden = false;
  });
  $('install').addEventListener('click', async () => {
    if (!deferredInstall) {
      setFeedback('No iPhone: Safari → Compartilhar → Adicionar à Tela de Início. No Android: menu do navegador → Instalar app.');
      return;
    }
    deferredInstall.prompt();
    await deferredInstall.userChoice;
    deferredInstall = null;
    $('install').hidden = true;
  });
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
  }

  // ---- inicio -------------------------------------------------------------------------
  if (token) connect();
  else setConnected(false);
})();
