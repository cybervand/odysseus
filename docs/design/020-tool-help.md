# 020 — Universal tool help: error-as-teaching for every tool

**Status:** Draft (2026-08-10). Design settled; nothing built.

## Problem

The gauntlet's recurring failure families are not capability failures —
they are *interface* failures: harmony arg mangling, pluralized tool
names, guessed action verbs, wrong arg shapes. A strong model shrugs
these off; the small local models this fork exists for retreat into
safe patterns (gemma's goal-loss, gpt-oss's compulsive planning) the
moment a tool returns a bare error. Today one tool teaches
(`manage_server` grew a `help` action in doc 017, with rollout to the
other `manage_*` tools left as an open item) and 72 don't.

## Prior art in-fork (the pattern already works)

- `manage_server help` — unknown actions return the manual (doc 017).
- Write-time health checks return advisory notes *in the tool result*
  (servers13) — the model reads them and self-corrects.
- PORT teaching — argv-port programs get told how `$PORT` works at the
  moment they get it wrong.

The common shape: **the harness teaches at the failure site, inside the
turn, without the model having to know help exists.** This doc
generalizes that shape to the whole registry.

## Design — three layers, all at the dispatch choke point

Everything hooks the single dispatch path (`execute_tool_block` →
delegate in `src/tool_execution.py`) via a new additive module
`src/tool_help.py`. **Zero edits to the 73 implementations** — this is
what "deploy a help function to all the tools" means mechanically: one
wrapper, every tool.

1. **Error-as-teaching (automatic — the load-bearing layer).** When a
   call fails validation (schema mismatch, missing required arg,
   unknown action, unknown tool name *with a close-match suggestion* —
   the pluralized-name family), the result is not a bare error but a
   generated manual excerpt: the failed field, the expected shape, and
   1–2 canonical examples. The model needs no initiative — the help
   arrives because it stumbled. This layer alone addresses the
   observed failure families.
2. **Explicit `help` — hierarchical and terse, like human CLI help
   (user requirement 2026-08-10).** Two scopes, mirroring
   `git help` / `git commit --help`, an idiom every model already
   knows from CLI corpora:
   - **Tool level** — `manage_server {action:"help"}` → a ~10-line
     synopsis: one line per action (`edit NAME … — change config`),
     ending with `help ACTION for details`. Never the full manual.
   - **Action level** — `{action:"help", topic:"edit"}` → only that
     action: required args, optional args, one canonical example.
     ~8 lines.
   The wrapper accepts the spellings models actually guess
   (`{action:"edit", help:true}`, `{action:"help edit"}`, bare
   `{"help": true}` on non-action tools) — a guessed help spelling
   must land on help, never on an error. The doc-017 open item
   (rollout to other `manage_*` tools) closes as a side effect.
   **Brevity is load-bearing, not style:** a wall-of-manual eats the
   small-model context budget that caused the fumbling in the first
   place; scoped help returns only the level asked for.
3. **Manual generation (single source of truth).** Help text is
   *rendered from the tool's JSON schema* (params, types, enums,
   required flags) so it can never drift from reality, plus a new
   curated `EXAMPLES` registry (1–2 canonical calls per action — the
   teaching gold; schemas describe shape, examples teach usage).
   Rendered compactly and cached; no LLM in the loop — help must be
   deterministic, instant, and free. Error-as-teaching (layer 1)
   reuses the same renderer at the same scope: a failed `edit` call
   returns *edit's* action-level help, not the tool manual.

### Dialect-aware examples (the fork specialty)

Examples are rendered through `dialect_profiles` so the model sees
calls in *its own* wire format — a qwen sees qwen-shaped calls, not
abstract JSON. Teaching in the wrong dialect is half-teaching; this is
the piece only this fork can do, and the reason upstreaming is
unlikely (same posture as the rest of the dialect work).

## Anti-goals

- **No new meta-tool** (`tool_help(name)` was considered): the RAG
  tool-index already handles "which tool do I use" discovery, and the
  registry stays at 73 — every added tool taxes exactly the weak
  models this helps.
- **No LLM-generated help at runtime** — determinism or nothing.
- **No prompt-side bloat**: help text lives in results on demand, never
  in the system prompt. The context budget of small models is part of
  why they fumble in the first place.

## Failure modes to guard

- **Help loops**: a stuck model calling help repeatedly. After N help
  responses for the same tool in one run, escalate the advice to "ask
  the user" (the doc-012 feedback-gating posture) rather than
  repeating the manual.
- **Teaching text mistaken for output**: manual excerpts must be
  clearly framed as harness guidance (the advisory-note framing from
  the health checks already solved this).

## Validation

Gauntlet A/B (same probes, wrapper on/off): tool-call success rate,
rounds-to-recovery after a malformed call, and stall rate. Log every
help trigger (tool, model, trigger layer) — the trigger histogram *is*
the map of which tools confuse which models, which then prioritizes
example curation. Success criterion: the harmony-mangling and
pluralized-name families convert from stalls into
self-corrected-next-round.

## Rollout

Behind `tool_help_enabled` (default on). Phase 1: validation-failure
teaching + unknown-tool suggestions. Phase 2: uniform `help` action.
Phase 3: dialect-shaped examples + the trigger-histogram feedback loop
into example curation.

## Decision log

- 2026-08-10 — Doc created from the user's ask ("deploy a help
  function to all the tools so models that have a tough time can get
  required help") + doc 017's manage_server-help open item. Dispatch-
  layer wrapper design settled; error-as-teaching named the load-
  bearing layer; meta-tool and runtime-LLM help rejected.
