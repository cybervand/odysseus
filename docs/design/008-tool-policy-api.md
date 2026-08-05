# 008 — Per-turn tool policy: record, expose, and tell the model

**Status:** Draft — approved direction (user, 2026-08-04), not yet built

## Problem

A turn's effective tool policy — terminal on/off, web search on/off,
workspace bound or not, which tools were disabled, forced, offered, and
sent — is decided across four layers (composer toggles, route logic,
intent classifier, force-offers) and **recorded nowhere**. Diagnosing
"the model says it has no terminal" took code archaeology three separate
times today; the model itself confabulates explanations ("I need a
workspace") because nothing tells it what is switched off; and the user
cannot see in the chat log what was enabled when a turn ran. Plugins/MCP
servers make this worse: their availability is equally invisible.

## Decision (to build)

One **policy snapshot** per agent turn, assembled where the loop already
knows everything (post-selection, pre-round-1):

```json
{
  "terminal": false, "web_search": true, "workspace": "/app/data/x" | null,
  "chat_mode": "agent", "model": "gpt-oss:20b",
  "disabled": ["bash"], "forced": [], "offered": 27,
  "mcp_servers": ["builtin_browser"],
  "source": {"terminal": "composer-toggle:false"}
}
```

Consumed four ways:
1. **Log line** `[agent-policy] ...` — one grep replaces today's forensics.
2. **Persisted** in the assistant message's metadata → visible in chat
   history/exports; an API reader (`GET /api/session/{id}` messages) gets
   it for free. Optional dedicated `GET /api/session/{id}/policy`.
3. **SSE event** (`type: "tool_policy"`) → UI can render per-turn chips
   (e.g. a struck-through terminal icon when off) next to the message.
4. **Model context**: one injected line when something load-bearing is OFF
   — "Note: the terminal is disabled for this turn (user toggle); say so
   if the task needs it instead of guessing." Kills the confabulation
   class ("I need a workspace", "I have no file access") at the root.

`source` records WHY (composer toggle, route default, admin policy,
non-admin block) so the answer to "who turned this off" is in the record.

## Rejected alternatives

- Logging only (no persistence/UI): fixes my debugging, not the user's
  "what was on when this ran" question.
- Telling the model its full tool list with reasons every turn: token
  cost; only OFF-state surprises earn context space.

## Open items

- Composer: surface the per-session bash pref visibly in the UI (the
  tri-state now EXISTS client-side; a visual "session override" hint on
  the toggle would complete it).
- Server-persisted per-session tool settings (the 5b follow-up): needs a
  deliberate design for WHICH callers' params mutate persistent state —
  a one-off API `allow_bash=true` must not silently become session
  policy. Until then the tri-state is client-side only.
- Extract `_compose_route_disabled_tools()` so route-gate tests exercise
  the real composition instead of textual pins (deferred from the
  2026-08-06 fix; the drifted test replica should be retired with it).
- Extend snapshot to plugin/MCP health (connected, tool count, disabled).

## Decision log

- 2026-08-04 — drafted from the allow_bash incident (bash silently off via
  composer toggle; no log, no UI, no model awareness — three components
  honest, one switch invisible).
- 2026-08-04 — phase 1 shipped: [agent-policy] log line (4b5f9839). First
  read exonerated the composer toggle and exposed the doc-mode stripper
  (the "third gate") in one grep.
- 2026-08-04 — phases 2-4 shipped (d7b5fb74, 84af3136): snapshot rides
  metrics into chat_messages.metadata.tool_policy; streams once as a
  tool_policy SSE event; agent_runs.list_runs() + admin GET
  /api/chat/runs for run discovery; scripts/watch_agent.sh attaches to
  the replay+live feed via /api/chat/resume with ody_ token or password
  auth. Observation now goes through the app's own API — thinking deltas
  included, which container logs never carried. Still open: UI chips for
  the tool_policy event; injecting policy DELTAS into model context
  ("terminal is NOW available") to break stale self-narrative anchoring;
  memory extractor must never memorize capability claims.
- 2026-08-06 — the `source` field SHIPPED, plus the guard this doc
  predicted. Trigger: the web-intent regex stripped bash + all file tools
  from a "build me a website (...images from the net...)" turn; gpt-oss
  truthfully claimed no shell mid-build; the [agent-policy] line's [:12]
  truncation hid the strip's tail and misdirected diagnosis at the UI
  toggle. Fixes: (1) both web-intent strips (main gate + chat-mode
  auto-escalation) now skip when `_message_signals_commands` fires or
  bash was explicitly granted — the same guard that fixed the doc-mode
  stripper; explicit denials/privileges/admin/plan/guide-only gates are
  never skipped. (2) Every disabled tool carries a `source` gate name
  end-to-end (route `_disable()` closure → ToolPolicy.sources →
  loop-level setdefaults → snapshot["source"] in SSE/metadata); the log
  line prints disabled_n + by_gate + the FULL list, never truncated.
  (3) Toggle-clobber fix, client-side tri-state: bash choices are stored
  per-session (odysseus-session-tools, LRU-capped); chat.js omits
  allow_bash entirely unless explicitly chosen for that session (legacy
  per-mode overrides honored), so browsers no longer clobber API-created
  sessions. Tests: tests/test_web_intent_tool_gate.py + updated frontend
  contract test.
