# 016 — Project ledger: evidence-backed checkboxes as the model's own memory

**Status:** Shipped (9d3d404c, deployed sync1 2026-08-14; companion
recovered_partial fix 16baff34). Validated live 2026-08-15: the ledger
injected on every turn of the qwen3.8 hawaii-history session and the
model retained its image URLs across turns — the exact failure this doc
was written from (gemma, 9bdad2b1) did not recur. Open: updater 502
during model contention wants a retry.

## Problem

Odysseus has two history pipelines and both serve the human. What the
**model** sees of its own past is a third pipeline nobody governs: next-turn
context is `session.history`, whose assistant entries hold only the
`content` column — i.e. only what the model *said aloud*. Everything it
did or thought is invisible to it one turn later.

Observed, gemma4 Vinterfjell run (session 9bdad2b1, 2026-08-06 — message
ids for receipts):

- A 13-round build turn persisted as five characters: `"Done."`
  (msg 97ee17c9; the 13 rounds of work live in `metadata.round_texts`,
  which the model never receives). The model's memory of its own turn is
  the word "Done."
- Tool results never cross turns. Gemma found image URLs via web_search,
  then next turn answered *"I don't actually have any image URLs in my
  current records"* (msg 620af9de) — **honest from inside its context**.
  The user had to paste the URLs back manually ("can you not read your
  own chat?", msg ab7dada0). The human was operating as the model's
  memory.
- The user's other questions the model could not answer without
  re-deriving from disk: "ok how much more left to do on the project"
  (msg 083caa69), "have you not gotten all the images already? list the
  files in your project now" (msg 8bd0abc3).
- Step-limit continuations need the user to type the memory in: "Continue
  from exactly where you left off … Do NOT repeat work" (msg c8fe9569).
- The failure has an evil twin: stream-recovery saves (`recovered_partial`
  metadata, msgs 6af088b0 = 35,710 chars / d6a95a35 = 32,094 chars) dump
  the raw stream — 16 paired `<think>` blocks — into `content` without
  passing `clean_thinking_for_save`. That text DOES re-enter the model's
  next-turn context, verbatim (no think-stripping exists in the
  model-bound path: `_sanitize_llm_messages` strips metadata keys, not
  think blocks). So the model's memory is either five characters or
  thirty-five thousand of the wrong ones, never the useful middle.
  (This is also the doc 014 display-side save-path bypass, now solved.)

Root cause in one line: **what the model said is persisted; what the model
did is not** — and for agent work, the doing is the substance.

## Decision

A session-scoped **project ledger**: an evidence-backed checklist of the
project's requirements, updated at the end of every agent run from feed-log
tool events (doc 014's second consumer — same log, model-facing instead of
human-facing), injected into context at the start of the next agent turn.
The verifier (doc 002) already builds exactly this shape — extract
requirements, match each against the actions record, emit MET/UNMET lines
— and then throws it away, keeping only the failure nudge
(`_parse_verifier_response`). The ledger is that checklist, persisted and
kept current.

Injected shape:

```
Project ledger — evidence-based record of YOUR prior work in this session.
Checked items are DONE — do not repeat them. Unchecked items are NOT done.
[x] skilodge/ created (bash mkdir, exit 0)
[x] backend app.py written — Flask + SQLite, routes /, /api/rooms
[~] images downloaded (2/5):
    [x] hero.jpg      (curl exit 0, 214KB, skilodge/static/img/hero.jpg)
    [x] rooms.jpg     (curl exit 0, 187KB)
    [ ] spa.jpg       — URL known: https://upload.wikimedia.org/...
    [ ] restaurant.jpg — URL known: https://upload.wikimedia.org/...
    [ ] bar.jpg       — no URL yet
[ ] frontend templates (step 2)
!! app.py exited 1 on last start — unaddressed
```

### Rules

1. **Evidence ticks boxes; claims never do.** A box checks only on
   effectful tool events with exit 0 (`_VERIFIER_EFFECTFUL_TOOLS` gate
   reused — read-only calls can't tick, same rule that killed the
   gpt-oss read-and-claim-victory dodge) and on verifier MET lines when a
   verifier ran. Model prose updates nothing. This is what keeps the
   ledger from becoming a confabulation anchor.
2. **Checked items carry their artifacts.** Paths, ports, URLs, sizes —
   the facts needed to *act on* completed work. A bare `[x] found URLs`
   would have left gemma exactly as stuck; the URLs ride on the line.
   Bounded per item.
3. **Countable requirements itemize.** When the count is knowable — the
   instruction enumerates N things, or evidence accumulates multiple
   instances of one action against a requirement — the box splits into
   per-item sub-boxes with a `[~] k/n` partial parent. A monolithic box
   lies in both directions on half-done work and loses the which-ones
   information (the exact thing the user had to interrogate for). Unchecked
   sub-items carry what is known toward finishing them (the URL, if found),
   so the model resumes mid-list without re-searching.
4. **A sub-item only checks with an artifact** (file path + size + exit
   code). Fabrication defense: gemma's five invented unsplash URLs
   (0/5 fetchable) would have produced five unchecked lines with dead-URL
   evidence, not a checked "images done" — the difference between
   downloaded and hallucinated, which the verifier once failed to see
   (document-world Kaffe pass).
5. **Failed is a first-class state.** `!! command exited N — unaddressed`
   stays on the ledger until an effectful action addresses it; failures
   can't be forgotten between turns (extends the verifier's
   unmissable-failure rule from `_build_actions_snapshot` across turns).
6. **Bounded.** The whole block capped (~2KB). It is a checklist, not a
   transcript: maximum memory per token, and it *instructs* (don't redo)
   rather than merely reminding.

### Mechanism

- **Requirements extraction**: once per project, on the first effectful
  agent turn — same extraction the verifier prompt performs (numbered
  steps, named files/paths, show/state/write instructions), as a small
  dedicated call. New user instructions on later turns append requirements.
- **Update**: at run end, mechanical matching of the run's feed-log
  `tool_end` events (already enriched with command/exit_code/output —
  `src/tool_execution.py`) against open ledger lines; verifier MET/UNMET
  lines fold in when the verifier ran. No extra model call on the common
  path.
- **Storage**: a `ledger` event kind in `feed_events.db` holding the full
  serialized ledger each update, latest-wins on assembly — append-only,
  per-session, survives restarts, lives beside its evidence; cached on the
  session object.
- **Injection**: assembled ledger inserted before the latest user message
  via `_insert_before_latest_user` (src/agent_loop.py) on agent turns of
  sessions that have one. Marked as harness-provided state, not model
  claims.
- **Companion fix (ships first)**: `recovered_partial` saves route through
  `clean_thinking_for_save`, hardened for multi-block content (N paired
  `<think>` blocks → one `metadata.thinking` with separators, clean
  reply). Closes the display bypass AND stops raw reasoning re-entering
  the model's context.

## Rejected alternatives

- **Prose digest of last turn's actions** (the first draft of this idea):
  more tokens for less instruction — a digest reminds but does not forbid
  re-doing, and re-fed raw outputs can trigger re-execution. The checklist
  states done-ness explicitly and mechanically replaces the "do NOT repeat
  work" message users type by hand.
- **Re-feeding round_texts / thinking into context**: the DeepSeek lesson
  (doc 009, `_merge_reasoning_for_persist` docstring) — echoed reasoning
  reinforces looping. Thinking is deliberately display-only; the ledger
  carries conclusions, never reasoning.
- **Feeding full tool transcripts forward**: token blowup, and
  `recovered_partial` is the accidental live demo of what raw re-entry
  does to a session.
- **Model-maintained ledger** (ask the model to keep its own TODO): claims
  would tick boxes — observed failure modes make this fatal (granite
  narrating completion with invented environment constraints, gemma
  fabricating URLs). The harness owns the pencil.
- **Memory system as the carrier**: memories are cross-session,
  user-level, retrieval-fuzzy; task state must be turn-accurate,
  session-scoped, and always present — a different organ.
- **Monolithic boxes for countables**: lies both directions on partial
  work; loses which-ones (rule 3 exists because of this).

## Validation

Planned:

- Unit: assembly from feed events (tick on exit-0 effectful, no tick on
  read-only or prose claims); itemization + `[~] k/n` parent; artifact
  lines survive serialization; `!!` persists until addressed; size cap;
  requirement append on new instructions; recovered_partial extraction
  (16-block corpus from msgs 6af088b0/d6a95a35 as fixtures).
- Live acceptance, gemma Vinterfjell rerun with new armor: the three
  fumbled questions become ledger lookups ("how much more left" → unchecked
  lines; "you have all the urls" → artifact lines; "is the server running"
  → last server state + port). Step-limit continuation resumes without
  repeating checked work and without a hand-typed memory prompt.

## Open items

- Steward (doc 017): ledger deltas are exactly report-by-exception — the
  3b reporter reads the ledger, not the transcript.
- Chat-mode turns still emit no feed events (doc 014 gap) — ledger is
  agent-turn only until that closes.
- UI mirror: the same ledger rendered as a checkbox panel for the human
  (shares the assembler; display concern, separate change).
- Cross-session projects: a ledger keyed to the project dir rather than
  the session would let a new chat pick up the work (doc 010 preview tie);
  deliberately out of v1.
- Requirement-extraction quality on small models: if the extractor is
  weak, the ledger inherits its blind spots — candidate for the qwen
  daily-driver regardless of the chat's model.

## Decision log

- 2026-08-06 — Drafted. Root finding: model's next-turn memory is the
  spoken transcript only ("Done.", 5 chars, 13 rounds of invisible work);
  recovered_partial identified as both the doc 014 save-path bypass and a
  raw-reasoning context leak. Checkbox form over prose digest (user);
  itemized sub-boxes for countables (user).
