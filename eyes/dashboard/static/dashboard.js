/* ── SuneelWorkSpace Control Center — dashboard.js ────────────────────── */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const CLIENT_ID = 'cc_' + crypto.randomUUID().replace(/-/g, '');
let ws = null;
let wsReady = false;
let feedPaused = false;
let allHistory = [];
const STAGES = ['brainstorm','plan','confirm','implement','test','wire'];

// ── WebSocket ──────────────────────────────────────────────────────────────
function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${protocol}://${location.host}/ws/${CLIENT_ID}`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    wsReady = true;
    updateStatusPill('pill-ws', true);
    log('system', '⚡', 'Connected to Control Center');
    // Kick off ping loop
    setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({type:'ping'})), 30000);
  };

  ws.onmessage = e => {
    try { handleMessage(JSON.parse(e.data)); }
    catch(err) { console.warn('WS parse error:', err); }
  };

  ws.onclose = () => {
    wsReady = false;
    updateStatusPill('pill-ws', false);
    log('warn', '⚠️', 'Disconnected — reconnecting in 3s…');
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => {
    updateStatusPill('pill-ws', false);
  };
}

function handleMessage(msg) {
  const { type } = msg;

  if (type === 'log') {
    log(msg.level || 'info', msg.icon || '·', msg.content || '');
  } else if (type === 'stage') {
    setStage(msg.stage, msg.status || 'active');
  } else if (type === 'progress') {
    // Progress updates can be shown in the feed
    log('info', '⟳', `${msg.stage}: ${msg.label || ''} ${msg.pct != null ? msg.pct+'%' : ''}`);
  } else if (type === 'system') {
    log('system', '⚡', msg.message || '');
  } else if (type === 'error') {
    log('error', '✗', msg.message || 'Unknown error');
    setRunning(false);
  } else if (type === 'confirm_request') {
    showConfirmPanel(msg.plan || {});
  } else if (type === 'result') {
    showResult(msg);
    setRunning(false);
    loadHistory();
  } else if (type === 'repair_complete') {
    const btn = document.getElementById('repair-btn');
    if (btn) { btn.disabled = false; btn.textContent = '🔧 Repair to 98%'; btn.classList.remove('repairing'); }
    log('system', '✓', `Health repair done — score: ${msg.score ?? '?'}, fixes: ${msg.fixes ?? 0}`);
    // Paint the ring directly from the repair score — don't re-fetch (live endpoint lags)
    const repairScore = Math.round(msg.score || 0);
    const circumference = 251.2;
    const ring = document.getElementById('ring-fill');
    if (ring) {
      ring.style.strokeDashoffset = circumference - (repairScore / 100) * circumference;
      ring.style.stroke = repairScore >= 80 ? 'var(--accent-green)' : repairScore >= 50 ? 'var(--accent-yellow)' : 'var(--accent-red)';
    }
    const label = document.getElementById('health-score-label');
    if (label) label.textContent = repairScore;
    const details = document.getElementById('health-details');
    if (details) details.innerHTML = `<div class="health-detail-row"><span>Status</span><span class="${repairScore>=80?'ok':repairScore>=50?'warn':'err'}">repaired</span></div>`;
    loadHistory();
  } else if (type === 'quick_action_complete') {
    log('system', '✅', `Quick action complete: ${msg.action}`);
    loadHistory();
  } else if (type === 'pong') {
    // heartbeat — ignore
  }
}

// ── Prompt Submission ──────────────────────────────────────────────────────
function submitPrompt(mode) {
  const prompt = document.getElementById('prompt-input').value.trim();
  if (!prompt) return;
  if (!wsReady) { log('warn','⚠️','Not connected — retrying…'); connectWebSocket(); return; }

  resetStages();
  clearFeed();
  hideConfirmPanel();
  hideResult();
  setRunning(true);
  log('info', '▶', `${mode === 'brainstorm' ? 'Brainstorm' : 'Execute'}: ${prompt.slice(0, 80)}`);

  ws.send(JSON.stringify({ type: 'execute', prompt, mode }));
}

function setRunning(running) {
  document.getElementById('btn-execute').disabled = running;
  document.getElementById('btn-brainstorm').disabled = running;
  document.getElementById('btn-execute').textContent = running ? '⏳ Running…' : '⚡ Execute';
}

// ── Stage Bar ──────────────────────────────────────────────────────────────
function setStage(stageName, status) {
  const el = document.getElementById(`stage-${stageName}`);
  if (!el) return;
  // Remove previous state classes
  el.classList.remove('active', 'done', 'skipped');
  el.classList.add(status);
}

function resetStages() {
  STAGES.forEach(s => {
    const el = document.getElementById(`stage-${s}`);
    if (el) el.classList.remove('active','done','skipped');
  });
}

// ── Execution Feed ─────────────────────────────────────────────────────────
function log(level, icon, content) {
  if (feedPaused) return;
  const feed = document.getElementById('execution-feed');
  const empty = feed.querySelector('.feed-empty');
  if (empty) empty.remove();

  const now = new Date();
  const ts = now.toTimeString().slice(0,8);

  const line = document.createElement('div');
  line.className = `feed-line ${level}`;
  line.innerHTML = `
    <span class="feed-ts">${ts}</span>
    <span class="feed-icon">${icon}</span>
    <span class="feed-body">${escHtml(content)}</span>
  `;
  feed.appendChild(line);
  feed.scrollTop = feed.scrollHeight;

  // Keep max 500 lines
  while (feed.children.length > 500) feed.removeChild(feed.firstChild);
}

function clearFeed() {
  document.getElementById('execution-feed').innerHTML = '<div class="feed-empty">Waiting for command…</div>';
}

function togglePause() {
  feedPaused = !feedPaused;
  const btn = document.getElementById('btn-pause');
  btn.textContent = feedPaused ? '▶' : '⏸';
  btn.title = feedPaused ? 'Resume' : 'Pause';
}

// ── Ollama ─────────────────────────────────────────────────────────────────
function ollamaRepair() {
  log('stage', '🔧', 'Running Ollama repair cycle...');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'quick_action', command: 'ollama-repair', action: 'ollama_repair' }));
  }
}

function ollamaLearn() {
  log('stage', '🧠', 'Running Ollama learning cycle...');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'quick_action', command: 'ollama-learn', action: 'ollama_learn' }));
  }
}

// ── Hermes Agent ───────────────────────────────────────────────────────────
function startHermes() {
  log('stage', '🤖', 'Starting Hermes Agent session...');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'quick_action', command: 'hermes-start', action: 'hermes_chat' }));
  }
}

function hermesNight() {
  log('stage', '🌙', 'Running Hermes night health check...');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'quick_action', command: 'hermes-night', action: 'hermes_night' }));
  }
}

// ── Confirm Panel ──────────────────────────────────────────────────────────
function showConfirmPanel(plan) {
  const panel = document.getElementById('panel-confirm');
  const content = document.getElementById('plan-content');
  panel.classList.remove('hidden');
  content.innerHTML = '';
  content.appendChild(renderPlan(plan));
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideConfirmPanel() {
  document.getElementById('panel-confirm').classList.add('hidden');
}

function confirmPlan(approved) {
  hideConfirmPanel();
  if (!wsReady) return;
  ws.send(JSON.stringify({ type: 'confirm_response', approved }));
  log('info', approved ? '✅' : '❌', approved ? 'Plan approved' : 'Plan rejected');
}

function renderPlan(plan) {
  const frag = document.createDocumentFragment();
  const steps = plan.steps || [];

  const titleEl = document.createElement('div');
  titleEl.style.cssText = 'font-weight:600;margin-bottom:8px;color:var(--text)';
  titleEl.textContent = plan.title || 'Execution Plan';
  frag.appendChild(titleEl);

  if (!steps.length) {
    const empty = document.createElement('div');
    empty.style.color = 'var(--text-dim)';
    empty.textContent = 'No steps defined.';
    frag.appendChild(empty);
  } else {
    steps.forEach((s, i) => {
      const row = document.createElement('div');
      row.className = 'plan-step';

      const num = document.createElement('span');
      num.className = 'plan-step-num';
      num.textContent = `${i + 1}.`;

      const body = document.createElement('div');
      const desc = document.createElement('div');
      desc.className = 'plan-step-desc';
      desc.textContent = s.action || '';
      body.appendChild(desc);

      if (s.command) {
        const cmd = document.createElement('span');
        cmd.className = 'plan-step-cmd';
        cmd.textContent = s.command;
        body.appendChild(cmd);
      }

      row.appendChild(num);
      row.appendChild(body);
      frag.appendChild(row);
    });
  }

  // Return a wrapper div containing the fragment (caller sets innerHTML of a container)
  const wrapper = document.createElement('div');
  wrapper.appendChild(frag);
  return wrapper;
}

// ── Result Panel ───────────────────────────────────────────────────────────
function showResult(meta) {
  const panel = document.getElementById('panel-result');
  const content = document.getElementById('result-content');
  const outcome = meta.outcome || 'unknown';
  const cls = outcome === 'pass' ? 'pass' : outcome === 'fail' ? 'fail' : 'partial';
  panel.classList.remove('hidden', 'pass', 'fail', 'partial');
  panel.classList.add(cls);

  content.innerHTML = '';

  const badge = document.createElement('div');
  badge.className = `result-badge ${cls}`;
  badge.textContent = outcome.toUpperCase();

  const durEl = document.createElement('div');
  durEl.className = 'result-stat';
  const durStrong = document.createElement('strong');
  durStrong.textContent = 'Duration: ';
  durEl.appendChild(durStrong);
  durEl.appendChild(document.createTextNode(
    meta.duration_ms ? `${(meta.duration_ms / 1000).toFixed(1)}s` : '—'
  ));

  const stagesEl = document.createElement('div');
  stagesEl.className = 'result-stat';
  const stagesStrong = document.createElement('strong');
  stagesStrong.textContent = 'Stages: ';
  stagesEl.appendChild(stagesStrong);
  stagesEl.appendChild(document.createTextNode(
    (meta.stages_completed || []).join(' → ') || '—'
  ));

  content.appendChild(badge);
  content.appendChild(durEl);
  content.appendChild(stagesEl);
}

function hideResult() {
  document.getElementById('panel-result').classList.add('hidden');
}

// ── Status Pills ───────────────────────────────────────────────────────────
function updateStatusPill(id, online) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('online', online);
  el.classList.toggle('offline', !online);
}

// ── Clock ──────────────────────────────────────────────────────────────────
function startClock() {
  const el = document.getElementById('cc-clock');
  function tick() { el.textContent = new Date().toTimeString().slice(0,8); }
  tick();
  setInterval(tick, 1000);
}

// ── Data Loaders ───────────────────────────────────────────────────────────
async function apiFetch(path) {
  try {
    const r = await fetch(path);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch(e) {
    console.warn(`API ${path} failed:`, e);
    return null;
  }
}

async function loadHealth() {
  const data = await apiFetch('/api/health');
  if (!data) return;
  const score = Math.round(data.score || 0);
  const circumference = 251.2;
  const offset = circumference - (score / 100) * circumference;
  const ring = document.getElementById('ring-fill');
  if (ring) {
    ring.style.strokeDashoffset = offset;
    ring.style.stroke = score >= 80 ? 'var(--accent-green)' : score >= 50 ? 'var(--accent-yellow)' : 'var(--accent-red)';
  }
  const label = document.getElementById('health-score-label');
  if (label) label.textContent = score;
  document.getElementById('health-details').innerHTML =
    `<div class="health-detail-row"><span>Status</span><span class="${score>=80?'ok':score>=50?'warn':'err'}">${data.status||'—'}</span></div>`;
}

async function loadSuggestions() {
  const data = await apiFetch('/api/suggestions');
  const el = document.getElementById('suggestions-list');
  if (!el) return;
  if (!data || !data.length) { el.innerHTML = '<div class="loading-dots">No suggestions</div>'; return; }
  el.innerHTML = '';
  data.forEach(s => {
    const item = document.createElement('div');
    item.className = 'suggestion-item';
    item.dataset.prompt = s.label || '';
    const dot = document.createElement('div');
    dot.className = `suggestion-priority ${escHtml(s.priority || 'medium')}`;
    const text = document.createElement('span');
    text.textContent = s.label || '';
    item.appendChild(dot);
    item.appendChild(text);
    item.addEventListener('click', () => useSuggestion(item.dataset.prompt));
    el.appendChild(item);
  });
}

function useSuggestion(text) {
  document.getElementById('prompt-input').value = text;
  document.getElementById('prompt-input').focus();
}

async function loadAgents() {
  const data = await apiFetch('/api/agent');
  const el = document.getElementById('agent-map');
  if (!el) return;
  const agents = (data && data.agents) ? data.agents : [
    {name:'Claude',  status:'active', task:'Responding', score:0.87},
    {name:'Codex',   status:'idle',   task:'Idle',        score:0.72},
    {name:'Gemini',  status:'off',    task:'Offline',     score:null},
  ];
  el.innerHTML = '';
  agents.forEach(a => {
    const item = document.createElement('div');
    item.className = 'agent-item';

    const dot = document.createElement('div');
    const dotStatus = ['active','idle','off'].includes(a.status) ? a.status : 'off';
    dot.className = `agent-dot ${dotStatus}`;

    const info = document.createElement('div');
    info.style.flex = '1';
    const nameEl = document.createElement('div');
    nameEl.className = 'agent-name';
    nameEl.textContent = a.name || 'Agent';
    const taskEl = document.createElement('div');
    taskEl.className = 'agent-task';
    taskEl.textContent = a.task || '';
    info.appendChild(nameEl);
    info.appendChild(taskEl);

    item.appendChild(dot);
    item.appendChild(info);

    if (a.score != null) {
      const scoreEl = document.createElement('div');
      scoreEl.className = 'agent-score';
      scoreEl.textContent = `${(a.score * 100).toFixed(0)}%`;
      item.appendChild(scoreEl);
    }
    el.appendChild(item);
  });
}

async function loadGoals() {
  const data = await apiFetch('/api/goals');
  const el = document.getElementById('goals-list');
  if (!el) return;
  const goals = Array.isArray(data) ? data : (data && data.goals ? data.goals : []);
  el.innerHTML = '';
  if (!goals.length) {
    const empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-dim);font-size:11px';
    empty.textContent = 'No active goals.';
    el.appendChild(empty);
    return;
  }
  goals.slice(0, 5).forEach(g => {
    const item = document.createElement('div');
    item.className = 'goal-item';
    const title = document.createElement('div');
    title.className = 'goal-title';
    title.textContent = g.title || g.name || String(g);
    const status = document.createElement('div');
    status.className = 'goal-status';
    status.textContent = g.status || 'active';
    item.appendChild(title);
    item.appendChild(status);
    el.appendChild(item);
  });
}

async function loadHistory() {
  const data = await apiFetch('/api/history');
  allHistory = (data && Array.isArray(data.history)) ? data.history : (Array.isArray(data) ? data : []);
  renderHistory(allHistory);
}

function renderHistory(items) {
  const el = document.getElementById('history-list');
  if (!el) return;
  el.innerHTML = '';
  if (!items.length) {
    const empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-dim);font-size:11px';
    empty.textContent = 'No history yet.';
    el.appendChild(empty);
    return;
  }
  items.slice(0, 20).forEach(h => {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.dataset.prompt = h.prompt || '';

    const promptEl = document.createElement('div');
    promptEl.className = 'h-prompt';
    promptEl.textContent = (h.prompt || '').slice(0, 60);

    const meta = document.createElement('div');
    meta.className = 'h-meta';

    const badge = document.createElement('span');
    const oc = h.outcome === 'pass' ? 'pass' : h.outcome === 'fail' ? 'fail' : 'partial';
    badge.className = `h-badge ${oc}`;
    badge.textContent = h.outcome || '?';

    const tsEl = document.createElement('span');
    const tsRaw = h.timestamp || h.ts || '';
    tsEl.textContent = tsRaw.slice(5, 16);

    meta.appendChild(badge);
    meta.appendChild(tsEl);

    if (h.duration_ms) {
      const durEl = document.createElement('span');
      durEl.textContent = `${(h.duration_ms / 1000).toFixed(1)}s`;
      meta.appendChild(durEl);
    }

    item.appendChild(promptEl);
    item.appendChild(meta);
    item.addEventListener('click', () => replayHistory(item.dataset.prompt));
    el.appendChild(item);
  });
}

function toggleHistory() {
  const wrap = document.getElementById('history-search-wrap');
  wrap.classList.toggle('hidden');
}

function filterHistory(query) {
  const q = query.toLowerCase();
  renderHistory(q ? allHistory.filter(h => (h.prompt||'').toLowerCase().includes(q)) : allHistory);
}

function replayHistory(prompt) {
  document.getElementById('prompt-input').value = prompt;
}

async function loadAutolab() {
  const el = document.getElementById('autolab-content');
  if (!el) return;
  const data = await apiFetch('/api/autolab');
  el.innerHTML = '';
  if (!data) {
    const msg = document.createElement('div');
    msg.className = 'loading-dots';
    msg.textContent = 'Unavailable';
    el.appendChild(msg);
    return;
  }

  function makeRow(label, val) {
    const row = document.createElement('div');
    row.className = 'autolab-row';
    const l = document.createElement('span');
    l.className = 'label';
    l.textContent = label;
    const v = document.createElement('span');
    v.className = 'val';
    v.textContent = String(val);
    row.appendChild(l);
    row.appendChild(v);
    return row;
  }

  el.appendChild(makeRow('Experiment queue', data.queue_depth || 0));
  el.appendChild(makeRow('Last run', data.last_run ? data.last_run.slice(0, 16) : 'Never'));

  if (data.recent_hypotheses && data.recent_hypotheses.length) {
    const hdr = document.createElement('div');
    hdr.className = 'autolab-queue';
    hdr.style.cssText = 'margin-top:8px;font-size:10px;color:var(--text-dim);margin-bottom:4px';
    hdr.textContent = 'Recent hypotheses';
    el.appendChild(hdr);
    data.recent_hypotheses.slice(0, 3).forEach(h => {
      const hyp = document.createElement('div');
      hyp.className = 'autolab-hyp';
      hyp.textContent = h;
      el.appendChild(hyp);
    });
  }
}

// ── Upgrade 7: Quick Actions ───────────────────────────────────────────────
const QUICK_ACTIONS = {
  'night-shift':    { cmd: 'dag-run orchestrator/dag/pipelines/night_shift.yaml', label: 'Night Shift' },
  'gap-scan':       { cmd: 'python3 evolution/gap_finder.py',   label: 'Gap Scan' },
  'challenge':      { cmd: 'python3 evolution/challenger.py',   label: 'Challenge Generation' },
  'screenshot':     { cmd: 'screenshot-take',                   label: 'Screenshot' },
  'model-health':   { cmd: 'model-health',                      label: 'Model Health Check' },
  'evolution-start':{ cmd: 'python3 evolution/engine.py cycle', label: 'Evolution Cycle' },
  'morning-brief':  { cmd: 'morning-brief',                     label: 'Morning Brief' },
  'workspace-ci':   { cmd: 'workspace-ci',                      label: 'Workspace CI' },
  'hermes-chat':    { cmd: 'hermes-start',                      label: 'Hermes Chat' },
  'hermes-night':   { cmd: 'hermes-night',                      label: 'Hermes Night Check' },
  'ollama-repair':  { cmd: 'ollama-repair',                     label: 'Ollama Repair' },
  'ollama-learn':   { cmd: 'ollama-learn',                      label: 'Ollama Learn' },
};

async function quickAction(action) {
  const config = QUICK_ACTIONS[action];
  if (!config) return;
  log('info', '⚡', `Quick action: ${config.label}`);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'quick_action', action }));
  } else {
    log('warn', '⚠', 'WebSocket not connected — reconnecting…');
    connectWebSocket();
  }
}

// ── Upgrade 7: Approval Queue Actions ─────────────────────────────────────
async function approveItem(queuedAt) {
  try {
    await fetch('/api/approvals/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queued_at: queuedAt }),
    });
    log('system', '✅', 'Item approved and fix triggered');
    loadApprovalQueue();
  } catch(e) {
    log('error', '✗', `Approval failed: ${e.message}`);
  }
}

async function rejectItem(queuedAt) {
  try {
    await fetch('/api/approvals/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queued_at: queuedAt }),
    });
    log('system', '✕', 'Item rejected');
    loadApprovalQueue();
  } catch(e) {
    log('error', '✗', `Rejection failed: ${e.message}`);
  }
}

// ── Upgrade 7: New Panel Loaders ───────────────────────────────────────────
async function loadApprovalQueue() {
  const el = document.getElementById('approval-body');
  if (!el) return;
  try {
    const res = await fetch('/widgets/approval');
    el.innerHTML = await res.text();
    const data = await apiFetch('/api/visual/status');
    const badge = document.getElementById('approval-count');
    if (badge && data) badge.textContent = data.approval_queue || 0;
  } catch(e) { el.textContent = 'Error loading approvals'; }
}

async function loadEvolutionPanel() {
  const el = document.getElementById('evolution-body');
  if (!el) return;
  try {
    const res = await fetch('/widgets/evolution');
    el.innerHTML = await res.text();
  } catch(e) { el.textContent = 'Evolution not started'; }
}

async function loadVisualPanel() {
  const el = document.getElementById('visual-body');
  if (!el) return;
  try {
    const res = await fetch('/widgets/visual');
    el.innerHTML = await res.text();
  } catch(e) { el.textContent = 'Visual monitor not running'; }
}

async function loadModelsPanel() {
  const el = document.getElementById('models-body');
  if (!el) return;
  try {
    const res = await fetch('/widgets/models');
    el.innerHTML = await res.text();
  } catch(e) { el.textContent = 'Model router not initialized'; }
}

// ── Enhancement 1: Health Repair ──────────────────────────────────────────
async function startHealthRepair() {
  const btn = document.getElementById('repair-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Repairing…'; btn.classList.add('repairing'); }
  log('info', '🔧', 'Starting 8-stage health repair pipeline…');
  try {
    const res = await fetch('/api/health/repair', { method: 'POST' });
    const data = await res.json();
    log('info', '▶', `Repair job started: ${data.job_id} (target: ${data.target}%)`);
  } catch (e) {
    log('error', '✗', `Failed to start repair: ${e.message}`);
    if (btn) { btn.disabled = false; btn.textContent = '🔧 Repair to 98%'; btn.classList.remove('repairing'); }
  }
}

// ── Test Suite Controls ────────────────────────────────────────────────────
async function loadTestsPanel() {
  const el = document.getElementById('tests-body');
  if (!el) return;
  try {
    const res = await fetch('/widgets/tests');
    // Content is server-rendered with html.escape() on all user-derived values
    el.innerHTML = await res.text();
  } catch(e) { el.textContent = 'Tests unavailable'; }
}

async function runTests() {
  log('info', '🧪', 'Running test suite…');
  try {
    const res = await fetch('/api/tests/run', { method: 'POST' });
    const data = await res.json();
    log('info', '▶', `Test run started: ${data.job_id}`);
    setTimeout(loadTestsPanel, 15000);
  } catch(e) { log('error', '✗', `Test run failed: ${e.message}`); }
}

async function runRepairLoop() {
  log('info', '🔧', 'Starting autonomous repair loop…');
  try {
    const res = await fetch('/api/tests/repair-loop', { method: 'POST' });
    const data = await res.json();
    log('info', '▶', `Repair loop started: ${data.job_id}`);
    setTimeout(loadTestsPanel, 60000);
  } catch(e) { log('error', '✗', `Repair loop failed: ${e.message}`); }
}

// ── Enhancement 2: Autolab Controls ───────────────────────────────────────
async function runAutolabExperiments() {
  log('info', '⚗', 'Triggering autolab experiment runner…');
  try {
    const res = await fetch('/api/autolab/run', { method: 'POST' });
    const data = await res.json();
    log('info', '▶', `Autolab runner started: ${data.job_id}`);
  } catch (e) {
    log('error', '✗', `Autolab run failed: ${e.message}`);
  }
}

async function generateHypotheses() {
  log('info', '💡', 'Generating new experiment hypotheses…');
  try {
    const res = await fetch('/api/autolab/generate', { method: 'POST' });
    const data = await res.json();
    log('info', '✓', `Hypotheses generated (${data.count ?? 0} lines)`);
    loadAutolabQueue();
  } catch (e) {
    log('error', '✗', `Hypothesis generation failed: ${e.message}`);
  }
}

async function loadAutolabQueue() {
  const el = document.getElementById('autolab-queue-list');
  if (!el) return;
  const data = await apiFetch('/api/autolab/experiments');
  el.innerHTML = '';
  const exps = (data && Array.isArray(data.experiments)) ? data.experiments : [];
  if (!exps.length) return;
  const hdr = document.createElement('div');
  hdr.className = 'autolab-queue-hdr';
  hdr.textContent = `Queue (${exps.length})`;
  el.appendChild(hdr);
  exps.slice(0, 5).forEach(exp => {
    const row = document.createElement('div');
    row.className = 'autolab-queue-item';
    const badge = document.createElement('span');
    badge.className = `alq-level alq-${(exp.level || 'safe').toLowerCase()}`;
    badge.textContent = exp.level || 'SAFE';
    const name = document.createElement('span');
    name.className = 'alq-name';
    name.textContent = (exp.name || '').slice(0, 55);
    row.appendChild(badge);
    row.appendChild(name);
    el.appendChild(row);
  });
}

// ── Keyboard Shortcuts ─────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  // Ctrl+Enter → Execute
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    submitPrompt('full');
  }
  // Ctrl+B → Brainstorm
  if ((e.ctrlKey || e.metaKey) && e.key === 'b' && !e.shiftKey) {
    const active = document.activeElement;
    if (active && active.id === 'prompt-input') {
      e.preventDefault();
      submitPrompt('brainstorm');
    }
  }
  // Escape → reject confirm
  if (e.key === 'Escape') {
    if (!document.getElementById('panel-confirm').classList.contains('hidden')) {
      confirmPlan(false);
    }
  }
});

// ── Utils ──────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Init ───────────────────────────────────────────────────────────────────
function init() {
  startClock();
  connectWebSocket();

  // Initial data loads
  loadHealth();
  loadSuggestions();
  loadAgents();
  loadGoals();
  loadHistory();
  loadAutolab();
  loadAutolabQueue();
  loadModelsPanel();
  loadEvolutionPanel();
  loadVisualPanel();
  loadApprovalQueue();
  loadTestsPanel();

  // Polling intervals
  setInterval(loadHealth,        30000);
  setInterval(loadSuggestions,   60000);
  setInterval(loadAgents,        15000);
  setInterval(loadGoals,         60000);
  setInterval(loadAutolab,       60000);
  setInterval(loadAutolabQueue,  90000);
  setInterval(loadModelsPanel,   60000);
  setInterval(loadEvolutionPanel, 30000);
  setInterval(loadVisualPanel,   45000);
  setInterval(loadApprovalQueue, 20000);
  setInterval(loadTestsPanel,   120000);

  // Check AI status via /api/status
  async function checkStatus() {
    const s = await apiFetch('/api/status');
    if (s) {
      updateStatusPill('pill-mcp', s.mcp === 'online');
      updateStatusPill('pill-ai',  true);
    }
  }
  checkStatus();
  setInterval(checkStatus, 30000);
}

document.addEventListener('DOMContentLoaded', init);
