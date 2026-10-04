/* JARVIS web remota — leve, sem frameworks */
(function () {
  const chat = document.getElementById('chat');
  const stateEl = document.getElementById('state');
  const tokenInput = document.getElementById('token');
  let token = localStorage.getItem('jarvis_token') || '';
  tokenInput.value = token;

  document.getElementById('save-token').onclick = () => {
    token = tokenInput.value.trim();
    localStorage.setItem('jarvis_token', token);
    refresh();
  };

  function add(who, text) {
    const whoEl = document.createElement('div');
    whoEl.className = who === 'USER' ? 'user' : 'jarvis';
    whoEl.textContent = who + ':';
    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = text;
    chat.appendChild(whoEl);
    chat.appendChild(body);
    chat.scrollTop = chat.scrollHeight;
  }

  async function api(path, method, payload) {
    const opts = { method: method || 'GET', headers: { 'X-Jarvis-Token': token } };
    if (payload) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(payload);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) { add('JARVIS', 'Token inválido. Confira e salve de novo.'); throw new Error('401'); }
    return res.json();
  }

  async function send() {
    const input = document.getElementById('text');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    add('USER', text);
    stateEl.textContent = 'PROCESSANDO…';
    try {
      const data = await api('/api/chat', 'POST', { text });
      add('JARVIS', data.reply || '(sem resposta)');
    } catch (e) { /* ja avisado */ }
    refresh();
  }

  document.getElementById('send').onclick = send;
  document.getElementById('text').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

  const micBtn = document.getElementById('mic');
  micBtn.onclick = async () => {
    if (micBtn.classList.contains('listening')) {
      await api('/api/stop', 'POST', {});
      micBtn.classList.remove('listening');
      micBtn.textContent = '🎤 FALAR';
    } else {
      const data = await api('/api/listen', 'POST', {});
      if (data.started) {
        micBtn.classList.add('listening');
        micBtn.textContent = '⏹ OUVINDO… (toque p/ parar)';
        add('JARVIS', 'Ouvindo no microfone do notebook…');
      }
    }
  };

  async function refresh() {
    try {
      const s = await api('/api/status');
      stateEl.textContent = s.state || '—';
      document.getElementById('st-cpu').textContent = s.cpu != null ? s.cpu.toFixed(0) + '%' : '--';
      document.getElementById('st-ram').textContent = s.ram_total_gb ? s.ram_used_gb + '/' + s.ram_total_gb + 'G' : '--';
      document.getElementById('st-mic').textContent = s.mic || '--';
      const mark = (id, ok) => {
        const el = document.getElementById(id);
        el.textContent = ok ? 'OK' : 'FALHA';
        el.className = ok ? 'ok' : 'bad';
      };
      mark('st-whisper', s.whisper);
      mark('st-qwen', s.llm);
      mark('st-piper', s.piper);
      if (s.state === 'READY' && micBtn.classList.contains('listening')) {
        micBtn.classList.remove('listening');
        micBtn.textContent = '🎤 FALAR';
      }
    } catch (e) { /* offline ou sem token */ }
  }

  refresh();
  setInterval(refresh, 4000);
})();
