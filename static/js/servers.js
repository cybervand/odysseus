// static/js/servers.js
// Named servers as a service (doc 017): the persistent chip strip above the
// chatbox + the API client the /server slash commands share.
//
// The strip is OWNER-scoped, not chat-scoped: a running server stays visible
// (and clickable) after the user leaves the chat that started it. A stopped
// server does not vanish — its chip says so and teaches the restart path
// (/server start <name>), which runs model-free.

const POLL_MS = 30000;

let _timer = null;

async function list() {
  const res = await fetch('/api/servers', { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`servers list failed: ${res.status}`);
  return res.json();
}

async function act(name, action) {
  const res = await fetch(`/api/servers/${encodeURIComponent(name)}/${action}`,
    { method: 'POST', credentials: 'same-origin' });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `${action} failed (${res.status})`);
  return body;
}

async function assignToSession(name, sessionId) {
  const fd = new FormData();
  fd.append('session_id', sessionId);
  const res = await fetch(`/api/servers/${encodeURIComponent(name)}/assign`,
    { method: 'POST', body: fd, credentials: 'same-origin' });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `assign failed (${res.status})`);
  return body;
}

async function logs(name) {
  const res = await fetch(`/api/servers/${encodeURIComponent(name)}/logs`,
    { credentials: 'same-origin' });
  if (!res.ok) throw new Error(`logs failed (${res.status})`);
  return res.json();
}

// ── Chip strip ────────────────────────────────────────────────────────────

function _prefillCommand(text) {
  const input = document.getElementById('message');
  if (!input) return;
  input.value = text;
  input.focus();
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function _chip(server) {
  const running = server.running;
  const listening = server.port_listening;
  const el = document.createElement(running && server.url ? 'a' : 'button');
  el.className = 'server-chip'
    + (running ? (listening ? ' server-chip-up' : ' server-chip-warm') : ' server-chip-down');

  const dot = document.createElement('span');
  dot.className = 'server-chip-dot';
  el.appendChild(dot);

  const label = document.createElement('span');
  label.className = 'server-chip-name';
  label.textContent = server.name;
  el.appendChild(label);

  const detail = document.createElement('span');
  detail.className = 'server-chip-detail';
  if (running) {
    detail.textContent = `:${server.port}`;
    el.href = server.url;
    el.target = '_blank';
    el.rel = 'noopener';
    el.title = listening
      ? `${server.name} — running on ${server.url}`
        + (server.chat_name ? ` (chat: ${server.chat_name})` : '')
      : `${server.name} — process is up but nothing listens on port ${server.port} yet`;
  } else {
    detail.textContent = 'stopped';
    el.type = 'button';
    el.title = `${server.name} is stopped — click to prefill "/server start ${server.name}"`;
    el.addEventListener('click', () => _prefillCommand(`/server start ${server.name}`));
  }
  el.appendChild(detail);
  return el;
}

async function refresh() {
  const strip = document.getElementById('server-strip');
  if (!strip) return;
  let data;
  try {
    data = await list();
  } catch {
    return; // transient — keep the last known strip rather than flashing empty
  }
  strip.replaceChildren();
  const servers = (data.servers || [])
    .sort((a, b) => (b.running - a.running) || a.name.localeCompare(b.name));
  for (const s of servers) strip.appendChild(_chip(s));
}

function init() {
  refresh();
  if (_timer) clearInterval(_timer);
  _timer = setInterval(refresh, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

const serversModule = { list, act, assignToSession, logs, refresh };
export default serversModule;
