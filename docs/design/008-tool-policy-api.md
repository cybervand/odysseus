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

- Composer: make the `>_` and web toggles' current state visibly sticky
  per chat (the regex silently deciding allow_bash is how today's
  confusion started).
- Extend snapshot to plugin/MCP health (connected, tool count, disabled).

## Decision log

- 2026-08-04 — drafted from the allow_bash incident (bash silently off via
  composer toggle; no log, no UI, no model awareness — three components
  honest, one switch invisible).
