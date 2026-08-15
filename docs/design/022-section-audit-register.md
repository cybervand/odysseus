# 022 — The section audit register: taking the app apart on purpose

**Status:** Living document — started 2026-08-15 (user-proposed campaign)

## Why this page exists

A month of incident-driven work proved something by accident: the one
part of the app that got WEEKS of sustained attention — the chat/agent
core — is now the strongest part of the app (docs 013–016: streaming,
persistence, thinking, feed log, ledger; all tested, all documented).
Everything else still gets fixed only when it breaks in front of us.
This register converts that accident into the method: take the app
apart ON PURPOSE, one section at a time, until every box is green.

The user's framing (2026-08-15): "take the entire app apart slowly in
different sections, the chat, the apps, almost everything, and work on
it one at a time."

## Rules

1. **Audit-and-stabilize, never teardown-rewrite.** Per section:
   inventory what it does → run it hard → fix what snags → write the
   tests it lacks → record its contract in its owning doc → move on.
   Rewrite only what the audit PROVES rotten. (Doc 021 posture,
   sectionized. This fork already carries one history-rewrite scar.)
2. **Verdicts are evidence-gated.** A section goes green on passing
   tests plus a completed workout, never on vibes — doc 016's ledger
   philosophy pointed at the codebase itself.
3. **One section per working session.** Slow is the strategy. Six weeks
   of this beats six months of whack-a-mole.
4. **The workout driver is the in-app Claude agent** (Anthropic endpoint;
   native adapter verified present in llm_core 2026-08-15, pending the
   user's API key). A competent agent removes attribution ambiguity:
   whatever it stumbles on is the app's bug, not the model's confusion.
   Until the key lands, workouts run via direct tool invocation (the
   fable_driver pattern from the 2026-08-15 audit).
5. **Register discipline:** every session that touches a section updates
   its row — date, what was exercised, what was found, verdict. A stale
   register is a lying register.
6. **Upstream corollary:** audited sections are safe to own and diverge;
   unaudited sections stay in cherry-pick-from-upstream mode.

## Verdict vocabulary

- **green** — workout completed, suite covers it, no known bugs.
- **in-progress** — actively being audited.
- **known-issues** — audited; bug list open (fix before green).
- **unaudited** — nothing systematic yet; reactive fixes only.

## The register

| # | Section | Scope (owning docs) | State | Notes (last touched) |
|---|---------|--------------------|-------|----------------------|
| 1 | Chat/agent core | stream, rounds, persistence, thinking, feed log, ledger (013, 014, 016) | **green*** | The accidental prototype of this method. *Open: feed phases 2/4, chat-mode events, terminal run_state, #5931 pick. (2026-08-15) |
| 2 | Tool layer | parse → guards → dispatch → results (009, 012, 015, 017) | **in-progress** | 2026-08-15 dogfooding audit: 8/8 parse clean; G1/M1/M2 fixed same day (audit1). Open: W1 write-diff + M3 query-body token weight — verify what _append_tool_results forwards; F1 stock-watermark filter for find_images. |
| 3 | Model adapters | llm_core dialects, thinking normalization, context windows (009, 013) | **known-issues** | qwen3.8 window split-brain fixed (ctxfix1) but the CLASS is open: every local model with native>32K has the same exposure — served-window detection from /api/ps is the real fix. qwen3-coder thinking-render bug open (suspect #5829). ANTHROPIC_MODELS list predates Claude 5. |
| 4 | Servers/registry + toolchain | bg_jobs, manage_server, doc 015 tiers (015, 017) | **known-issues** | Young, fast-moving; 2026-08-15 found 3 bugs in one evening (fixed). Gate script still relaunches retired skilodge. Needs a consolidation pass + registry workout. |
| 5 | Documents | create/edit/diff/library, doc tools (003, 004, 005) | **unaudited** | Most load-bearing app feature, least exercised by recent sessions. **First full workout target.** |
| 6 | Notes | note routes, reminders | **unaudited** | Small; quick win. |
| 7 | Calendar | caldav sync, events, defaults | **unaudited** | Upstream just made creation transactional (#5806, picked). |
| 8 | Memory system | memories, vectors, recall injection | **unaudited** | Store-overwrite guard picked (#5831). |
| 9 | Skills | manage_skills, teacher escalation, skill index | **unaudited** | Frontmatter escape + action-required picks landed. sideways-timeline skill shows learned skills can be too vague to help — audit should define a quality bar. |
| 10 | Email | accounts, IMAP, summaries, urgency, scheduling | **unaudited** | Big, but upstream serialization-hardened it this month (6 picks). Audit-light pass. |
| 11 | Search/research/images | web_search, deep research, find_images, gallery | **unaudited** | F1 (watermark filter) belongs here too. find_images fail-status investigation open. |
| 12 | Vision pipeline | attachments, rehydration, OCR, browser MCP (019) | **unaudited** | Rehydration fixed (ebeac24a); read_attachment tool still roadmap. qwen3.8 vision untested in-app. |
| 13 | Background jobs/scheduler | task_scheduler, bg_monitor, pollers | **unaudited** | bg-followup "__ops__ not found" warning spam observed 2026-08-14. |
| 14 | Auth/settings/admin | auth routes, settings API, tool policy surface (008) | **unaudited** | Settings path gotcha (/api/auth/settings) already cost one bug (verifierfix2). |
| 15 | UI surfaces | chat renderer, sidebar, pickers, PWA/SW | **last on purpose** | Sits on everything else; audit after the layers beneath are green. SW shell-mismatch lesson (swfix1) lives here. |

## Campaign order

Tool layer (finish) → Documents → Servers/registry → Notes → Calendar →
Memory → Skills → Model adapters (served-window fix) → Email →
Search/images → Vision → Background jobs → Auth/settings → UI.

Order rationale: dependency-first (everything rides tools), then the
most load-bearing least-tested feature (documents), then the youngest
code (servers). UI last because auditing it before its foundations
means auditing it twice.

## Rejected alternatives

- **Full teardown/rewrite:** the classic death march; discards a month
  of hardening; the audit already shows most sections need tests and
  fixes, not replacement.
- **Keep reactive-only:** a month of evidence says pain picks the same
  three sections repeatedly while the other twelve rot silently.
- **Parallel multi-section sweeps:** splits attention exactly the way
  swarm peer-chatter splits small models; one section at a time is the
  point.

## Decision log

- 2026-08-15 — register created. Rows seeded with honest current state:
  1 green (chat core), 1 in-progress (tools), 2 known-issues, 11
  unaudited. Workout driver: Claude-agent pending API key; fable_driver
  direct invocation until then.
