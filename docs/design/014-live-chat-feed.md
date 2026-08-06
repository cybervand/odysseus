# 014 — Live chat feed: the proper design

**Status:** Design + spike only (user directive 2026-08-06: "we dont
deploy this round, its purely for design and testing")

## Why this page exists

Two days of incidents proved the feed's guarantees are an accident of
patches, not an architecture. Each fix was correct alone; together they
are four sources of truth that can disagree:

1. **DB rows** (user msgs at POST, assistant at run END)
2. **In-memory run buffer** (agent_runs — dies with the process)
3. **Checkpoint files** (round-level, promoted on history load)
4. **The client's DOM** (whatever it happened to witness)

Refresh renders #1, live renders #2, crash recovery renders #3, and the
user believes #4. The 2026-08-06 incidents (vaporized reply, time-travel
refresh, replayed "thinking" mistaken for live, eaten composer text) are
all disagreements between these stores.

## The contract a chat feed must satisfy

- **Durability**: anything the user ever SAW is permanently recoverable.
- **Truthful refresh**: reload renders exactly the current state — never
  the past, never a replay disguised as the present.
- **Liveness**: every viewing client converges on "now" without manual
  action, including runs started by OTHER clients (API, watcher, phone).
- **Attribution**: replayed content is visibly replay; live is live.
- **Crash equivalence**: a killed process loses at most the tokens not
  yet flushed — never a whole reply.

## Current method (production today), honestly

```
user msg ──POST──> persisted immediately (chat_helpers.add_user_message)
                └─> detached run (agent_runs.start) ── SSE deltas ──> buffer (RAM)
                                        │                             │
                       every round ─────┼──> checkpoint file          ├─> subscribers
                       run end ─────────┴──> assistant DB row         │   (replay buffer + live)
client: 6s poller → stream_status → resumeStream → replay+live
        liveness watchdog (silence + runs-API cross-check)
        history load → promote orphaned checkpoints → DB rows
```

Strengths: user-msg durability is right; detached runs are right; the
observation API (doc 008) is right. Weaknesses: the buffer is RAM-only;
assistant durability needed the checkpoint patch; attach is client-poll
(≤6s lag) not push; replay is pixel-identical to live; a client never
learns about OTHER clients' messages except by reload; every guarantee
is enforced in a different subsystem.

## Alternatives considered

### A. Event-log-first (event sourcing lite)
Append EVERY feed event (user msg, round delta, tool card, run state)
to a durable per-session log with a monotonically increasing `seq`
(SQLite table). All consumers read the SAME log:
- History = render events 0..head.
- Live = tail the log from your last seq (SSE `Last-Event-ID` — this is
  literally what the SSE standard's resume mechanism is FOR).
- Replay vs live = "my position < head" vs "at head" — the badge is a
  comparison, not a feature.
- Crash loses only unflushed tokens; no checkpoint files, no RAM buffer
  as truth (RAM becomes a cache).
This is the ChatGPT/Kafka-shaped answer: one ordered truth, many tails.

### B. WebSocket hub
Bidirectional per-client channel; server PUSHES message-created /
run-started / delta events to every subscriber of a session. Solves
cross-client visibility (an API-injected message appears in the open tab
instantly) and enables acks/typing. Cost: connection lifecycle, auth,
reconnect — and it does NOT solve durability by itself; it still wants
the log underneath.

### C. Polling-only
Interval refetch of history+partial. Simple, robust, high-latency, high
load. Rejected as primary; kept as degraded fallback.

### D. Hybrid: durable log + push channel  ← RECOMMENDED
Event log (A) as the ONLY source of truth; a push channel (SSE with
Last-Event-ID is sufficient — WS optional later) that just tails it.
Clients render exclusively from log events: cold load, refresh, resume,
live, and observer-watching become ONE code path ("render from seq N,
keep tailing"). The four stores collapse to one plus caches.

## Spike (tested, not deployed)

`tests/test_event_log_spike.py` contains a working prototype EventLog
with the exact semantics above and tests proving: append/tail ordering,
resume-from-seq (no gaps, no dupes), replay/live boundary detection,
crash-equivalence (log survives "process death"), and multi-consumer
independence. It is deliberately dependency-free so promotion into
`src/` later is mechanical.

## The timeline contract (user, 2026-08-06)

The feed must be renderable as a full timeline — what the model thought,
what ran, which tools, and how long each phase took:

```
19:00:01            User: hi build X for me
19:00:01-19:00:30   Agent: thought: the user is asking me to build X...
19:00:30-19:01:05   Agent: [tools: bash, python, find_images] replied: Hi! Absolutely...
```

This falls out of the log for free IF every event carries a timestamp
and a kind. Canonical event kinds:

| kind | payload | timeline meaning |
|---|---|---|
| user_msg | text | `HH:MM:SS User: ...` |
| thinking | delta text | contiguous run → one `thought:` span (first..last ts) |
| tool_start / tool_end | tool, args head / result head | collected per reply → `[tools: a, b]`; per-tool spans available |
| reply | delta text | contiguous run → one `replied:` span |
| run_state | started/done/interrupted | phase boundaries, badges |

The CURRENT pipeline cannot produce this view: thinking deltas are
unstamped, tool timing exists only in container logs, and durations die
with the stream. In log-world the timeline is a pure function
`render_timeline(events)` — proven in the spike, which reproduces the
example above from raw events, to the second.

## Migration sketch (future, NOT this round)

1. Introduce `feed_events` table + writer, DUAL-writing alongside the
   current pipeline (no behavior change).
2. Move `/api/chat/resume` to log-tail with Last-Event-ID.
3. Move history rendering to the log; DB message rows become a
   derived/materialized view (kept for compat).
4. Retire checkpoint files and the RAM-buffer-as-truth; retire the 6s
   attach poller in favor of an always-open session tail.

## Decision log

- 2026-08-06 — page created after the vaporized-reply incident. Current
  method stays in production; spike lives in tests only. Hybrid (D)
  selected as the target; SSE+Last-Event-ID chosen over WebSockets for
  the first cut (keeps the existing SSE rendering path and auth).
