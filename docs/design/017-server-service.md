# 017 — Named servers as a service: port range, ownership, panel, query

**Status:** Draft (approved direction 2026-08-07, user + Claude design session)

## Problem

Agent-launched servers are half a feature. The registry (`src/bg_jobs.py`,
doc 014 follow-on) tracks name/command/cwd/port — but `port` is
**self-reported metadata**: nothing allocates it, validates it, or passes it
to the process. Observed 2026-08-07: skilodge's registry entry says 8091
while its `app.py` hardcodes 8090 (`app.run(port=8090)`), so the deploy
health-probe reported a healthy server as down. The tool's own list-action
example (`bg_job_tools.py` ~L84) teaches `"port": 8090` — models copy
examples, so drift is trained in. Three further failures, all observed on
copperwarehouse:

- **Invisible cross-chat sprawl.** servers.json holds skilodge (running)
  plus qwenmax-lodge and granite-vinterfjell (dead, registered forever —
  `server_stop` never deletes). The user has no surface that shows what is
  running, from which chat, on which port.
- **Fake ops owner.** Deploy-relaunched servers carry
  `session_id: "__ops__"`; `bg_monitor` retry-spams
  `bg-followup failed: 'Session __ops__ not found'` on every boot
  (2026-08-07 boot log, 12+ lines per sweep).
- **Learned helplessness** (the doc-003 failure family): models forget
  their own servers exist, refuse to edit them ("I can't edit this"), or
  resign on "my port is taken" — because nothing tells them the server is
  THEIRS, where its code lives, or that a busy port is usually their own
  process.

## Decision

Make named servers a first-class service with allocated ports, explicit
ownership, a user-facing panel, and an interrogation verb.

### 1. Reserved port range + allocation (`src/bg_jobs.py`)

- `ODYSSEUS_SERVER_PORT_RANGE` env, default `13000-13999`. Cookbook's
  model-serving allocator walks up from 8000 (`cookbookPorts.js`) — no
  collision. On br1 macvlan the container owns its IP, so the whole range
  is LAN-reachable with zero docker changes.
- `server_start` allocates the lowest free port in range (free = not
  registered to another server AND not listening). A named server keeps
  its port across restarts — stable URLs. A requested out-of-range port is
  refused with a teaching error.
- The launched process gets `PORT=<assigned>` in its environment
  (`launch()` grows an `env` param). Apps that follow the universal
  convention bind correctly with no model effort.
- **Truth-check:** a few seconds after start, probe the assigned port. Not
  listening → the tool result says so with the fix ("your app must read
  the PORT env var or bind {port}"), so drift becomes in-turn feedback
  instead of a lying registry.
- **Diagnosing conflicts, never reporting them:** every port error names
  the cause and next action — "13002 is your own server 'skilodge', still
  running; restart applies your code edits" / "13002 is busy; you are
  assigned 13003". No bare "address in use" ever reaches the model.

### 2. Ownership + mutable chat attachment (`src/bg_jobs.py`, `bg_job_tools.py`)

- Server records gain `owner` (the session's owner at registration).
  **Capability follows the owner, attachment follows the session**: verbs
  are owner-scoped (a fresh chat by the same user can manage the server
  immediately), while `session_id` is presentation — manifest sections,
  panel attribution, followups. Today the registry is global — chat A can
  kill chat B's server by name; owner scoping closes that (admin sees all).
- **Attachment is mutable** (the messed-up-chat scenario: user abandons a
  poisoned chat, opens a fresh one, takes the server along):
  `server_assign(name, target_session_id)` with ownership checked on both
  ends. Reached three ways — panel "assign to chat" (+ one-click "attach
  to current chat"), the `adopt` tool verb
  (`{"action": "adopt", "name": ...}`) so the user can say "take over my
  skilodge server" in-chat, and `POST /api/servers/{name}/assign`
  underneath both. Never implicit: touching a server from another chat
  does NOT reattach it — attribution must not jump silently.
- A first-class `SYSTEM_OWNER = "__system__"` replaces the fake
  `__ops__` session id for boot/deploy relaunches; `bg_monitor` followups
  skip system-owned jobs (kills the retry-spam), and the panel renders
  "system" instead of a dangling chat link.

### 3. Ownership awareness injection (doc-003 pattern, `agent_loop`)

Two-section manifest, mirroring doc 003's final form: **this chat's
servers** in full detail — name, port, status, cwd — worded as agency
("Your servers — you started these; the code lives in {cwd}; edit it
freely; `restart` applies your edits"), then **your servers from other
chats** as name + port + "use adopt to take one over". A fresh chat
always knows the user's servers exist and knows the verb to claim one.
Prevents duplicate-server sprawl and the "I can't edit this" refusal. NO
per-user caps — this is a homelab; the range is the backstop.

### 4. User-facing panel (`routes/server_routes.py` — new additive module)

- `GET /api/servers`: `server_list()` joined with sessions for
  `chat_name`/`chat_id`, owner-scoped, plus assigned port, URL, running /
  listening / responding, uptime, cwd. `POST /api/servers/{name}/stop`,
  `/restart`, `/remove`, `/assign` with the same ownership check.
- Frontend "Servers" panel (mirror `cookbookRunning.js` patterns): per
  server — status badge, clickable `http://<host>:<port>` link,
  owning-chat name + jump link, logs peek (`server_logs`), stop / restart
  / remove buttons, and "assign to chat" (+ "attach to current chat"
  shortcut when the panel is opened inside a chat).
- **`/server` slash-command family** (`slashCommands.js` registry, parent/
  sub style like `/chats`): `/servers` list, `/server
  stop|restart|remove|adopt|logs|open|query <name>`. Runs frontend→API
  with NO model in the loop — in the messed-up-chat scenario the user can
  `/server adopt skilodge` even though the chat's model is confused.
  Panel, slash commands, and the model tool are three doors over the same
  owner-scoped authority. Honest badges: "registered but NOT listening" is shown
  to the user, not just the model.

### 5. `query` verb (`bg_job_tools.py`)

`{"action": "query", "name": ..., "path": "/...", "method": "GET|POST",
"body": ...}` → HTTP request to `127.0.0.1:<registered port>` only.
Returns status, content-type, first 8 KB (marked truncated), elapsed ms.
Path must start with `/`; redirects not followed off-host; short timeout;
response framed as untrusted content. No SSRF surface (targets only
registry-known local ports) and no web-toggle dependency — a no-bash
session can finally verify its own server. Doubles as the panel's
"responding" probe and as verifier/ledger evidence (docs 002/016).

### 6. `remove` verb + registry hygiene

Deletes the servers.json entry (kills first if running). `stop` keeps the
entry (deliberate: restartable); `remove` is the actual delete the
registry never had.

### 7. `autostart` + boot reconciler (doc-015 pattern)

Servers flagged `autostart: true` are relaunched by Odysseus on app boot
(as the app uid — the 2026-08-06 EPERM lesson). Retires the deploy
script's hand-written skilodge relaunch step; deploys stop silently
killing the user's servers.

## Rejected alternatives

- **Per-user server cap** — enterprise reflex, wrong for a homelab; the
  port range itself bounds runaway loops, and teaching errors at
  exhaustion beat quotas before it (user, 2026-08-07).
- **Client-side port pick (cookbook style) for agent servers** — the model
  is the client here; self-reporting is the bug, not the fix.
- **Scanning app source for hardcoded ports and rewriting** — fragile,
  language-specific, and PORT-env injection + truth-check feedback gets
  the same outcome through the model's own loop.
- **Docker port publishing changes** — unnecessary on br1 macvlan.

## Validation

Planned: unit tests for allocation (lowest-free, stability across
restarts, out-of-range refusal, exhaustion error), ownership scoping,
query guardrails (path validation, size cap, non-registered name);
deterministic lab check that PORT env reaches the child; acceptance on
copperwarehouse — model starts a Flask app with no port in code beyond
`os.environ["PORT"]`, panel shows it attributed to the right chat, query
returns 200, container restart revives it via autostart.

## Open items

- **Stable proxied URLs** (`/serve/<name>/` in-app reverse proxy):
  permanent links independent of ports, plays well with a future Tailscale
  sidecar — but path-prefix-blind generated apps break under it. Needs its
  own decision record before build.
- Migration: existing entries (skilodge 8090, qwenmax-lodge 3000) are
  grandfathered with their stored ports; range applies to new
  registrations.
- skilodge registry port corrected to 8090 as part of shipping this.

## Decision log

- 2026-08-07 — Doc created from design session (port range, panel, query,
  ownership awareness; cap explicitly rejected). Not yet built.
- 2026-08-07 — Mutable chat attachment added (panel assign, `adopt` verb,
  assign API; two-section manifest): capability follows owner, attachment
  follows session, reassignment always explicit.
- 2026-08-07 — `/server` slash-command family added: user-driven access to
  the same verbs, model-free (works even when a chat's model is unusable).
