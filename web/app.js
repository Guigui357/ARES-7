/* ARES-7 Mobile/PWA — sem dependências externas. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const chat = $('chat');
  const stateEl = $('state');
  const tokenInput = $('token');
  const feedback = $('feedback');
  let token = localStorage.getItem('ares7_token') || '';
  tokenInput.value = token;
  let deferredInstall = null;
  let recognition = null;

  const setFeedback = message => { feedback.textContent = message || ''; };
  function add(who, text) {
    const welcome = chat.querySelector('.welcome');
    if (welcome) welcome.remove();
    const item = document.createElement('article');
    item.className = 'message ' + (who === 'USER' ? 'user' : 'ares');
    const label = document.createElement('div');
    label.className = 'speaker';
    label.textContent = who === 'USER' ? 'VOCÊ' : 'ARES-7';
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = String(text);
    item.append(label, body);
    chat.appendChild(item);
    chat.scrollTop = chat.scrollHeight;
  }
  async function api(path, method = 'GET', payload) {
    const opts = { method, headers: { 'X-Ares7-Token': token } };
    if (payload !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(payload);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      setFeedback('Token inválido ou ausente. Confira o token e toque em Conectar.');
      throw new Error('Token inválido');
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Erro HTTP ${res.status}`);
    return data;
  }
  async function connect() {
    token = tokenInput.value.trim();
    if (!token) { setFeedback('Digite o token configurado no notebook.'); return; }
    localStorage.setItem('ares7_token', token);
    try {
      await api('/api/ping');
      stateEl.textContent = 'ONLINE';
      stateEl.classList.add('online');
      setFeedback('Conectado ao ARES-7.');
      await refresh();
    } catch (err) {
      stateEl.textContent = 'OFFLINE';
      stateEl.classList.remove('online');
      setFeedback(err.message || 'Não foi possível conectar. Confira Wi-Fi, endereço e token.');
    }
  }
  $('save-token').addEventListener('click', connect);
  tokenInput.addEventListener('keydown', e => { if (e.key === 'Enter') connect(); });

  async function send() {
    const input = $('text');
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    add('USER', message);
    stateEl.textContent = 'PROCESSANDO…';
    $('send').disabled = true;
    try {
      const data = await api('/api/chat', 'POST', { text: message });
      add('ARES-7', data.reply || '(sem resposta de texto)');
      setFeedback('');
    } catch (err) {
      add('ARES-7', `Não consegui concluir: ${err.message}`);
    } finally {
      $('send').disabled = false;
      refresh();
    }
  }
  $('send').addEventListener('click', send);
  $('text').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
  $('clear').addEventListener('click', async () => {
    try {
      await api('/api/clear', 'POST', {});
      chat.textContent = '';
      add('ARES-7', 'Contexto da conversa limpo. A memória permanente não foi apagada.');
    } catch (err) { setFeedback(err.message); }
  });

  const micBtn = $('mic');
  micBtn.addEventListener('click', async () => {
    try {
      if (micBtn.classList.contains('listening')) {
        await api('/api/stop', 'POST', {});
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤 MICROFONE DO NOTEBOOK';
      } else {
        const data = await api('/api/listen', 'POST', {});
        if (data.started) {
          micBtn.classList.add('listening');
          micBtn.textContent = '⏹ PARAR MICROFONE DO NOTEBOOK';
          setFeedback('O notebook está ouvindo; para usar o microfone do celular, use “Ditar no celular”.');
        } else {
          setFeedback('O ARES-7 não conseguiu iniciar a escuta. Confira o estado no notebook.');
        }
      }
    } catch (err) { setFeedback(err.message); }
  });

  // Usa reconhecimento de fala do navegador, quando disponível; não envia áudio bruto.
  $('dictate').addEventListener('click', () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setFeedback('Este navegador não oferece ditado por voz compatível. Use o microfone do teclado do celular ou o microfone do notebook.');
      return;
    }
    if (recognition) { recognition.stop(); return; }
    recognition = new SpeechRecognition();
    recognition.lang = 'pt-BR';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    $('dictate').classList.add('listening');
    $('dictate').textContent = '⏹ OUVINDO NO CELULAR…';
    setFeedback('Fale agora. O reconhecimento depende do suporte e das permissões do navegador.');
    recognition.onresult = event => {
      const transcript = event.results[0][0].transcript;
      $('text').value = transcript;
      setFeedback('Texto reconhecido. Revise e toque em Enviar.');
      $('text').focus();
    };
    recognition.onerror = event => setFeedback(`Falha no ditado: ${event.error}. Você também pode usar o microfone do teclado.`);
    recognition.onend = () => {
      recognition = null;
      $('dictate').classList.remove('listening');
      $('dictate').textContent = '🎙️ DITAR NO CELULAR';
    };
    try { recognition.start(); } catch (err) { setFeedback(err.message); recognition = null; }
  });

  async function refresh() {
    if (!token) return;
    try {
      const s = await api('/api/status');
      stateEl.textContent = s.state || 'ONLINE';
      stateEl.classList.add('online');
      $('st-cpu').textContent = s.cpu != null ? `${Math.round(s.cpu)}%` : '--';
      $('st-ram').textContent = s.ram_total_gb ? `${s.ram_used_gb}/${s.ram_total_gb} GB` : '--';
      const mark = (id, ok) => {
        const el = $(id); el.textContent = ok ? 'OK' : 'OFF';
        el.className = ok ? 'ok' : 'bad';
      };
      mark('st-whisper', s.whisper);
      mark('st-qwen', s.llm);
      mark('st-piper', s.piper);
      if (s.state === 'READY' && micBtn.classList.contains('listening')) {
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤 MICROFONE DO NOTEBOOK';
      }
    } catch (_) {
      stateEl.textContent = 'DESCONECTADO';
      stateEl.classList.remove('online');
    }
  }

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

  if (token) connect();
  window.setInterval(refresh, 5000);
})();
