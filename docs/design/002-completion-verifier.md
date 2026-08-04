# 002 — Agent completion verifier

**Status:** Shipped; evolving (upstream base + rounds ba6522f5, 3917a9fa, 0cf537a9)

## Problem

Small local models claim completion they didn't do. Live specimens, in
escalating order: a done-claim after calling only the zero-argument
`get_workspace` tool; "the poems have been written" with zero write calls;
"I edited the fragment shader to add smoke" after a failed edit followed by
two reads. A completion claim is cheap; the loop needs an independent check.

## Decision

Fresh-context verifier subagent (`agent_loop._run_verifier_subagent`): a
second model instance with NO shared history reads the user request + a
compact record of tool executions (`_build_actions_snapshot`) and outputs
per-requirement MET/UNMET lines. Design pillars, each earned by a live
failure:

1. **Fail-open** (upstream): a broken verifier must not block a valid
   completion. Every hardening below narrows the fail-open path without
   removing it.
2. **UNMET-line parsing** (`_parse_verifier_response`): small judges
   enumerate evidence well but botch the final verdict boolean; trust the
   per-requirement lines over the VERIFICATION line.
3. **Reasoning starvation fix** (ba6522f5): gpt-oss at default effort spent
   the whole 900-token budget thinking and returned empty content → empty
   verdict → silent pass. Non-streaming /v1 requests low reasoning effort
   for gpt-oss; verifier retries once at 1600 tokens (a bigger budget also
   bypasses the llm response cache — an identical retry would replay the
   cached empty string) and logs a warning before failing open.
4. **Effectful-only flag clearing** (3917a9fa,
   `_round_clears_verifier_flag`): after a verifier FAIL, only tools in
   `_VERIFIER_EFFECTFUL_TOOLS` clear the pending flag. Previously ANY tool
   round cleared it — a model dodged a flag by running two reads and then
   re-claiming. Reading is not fixing; claiming is not doing (the pushback
   message now says both).
5. **Diff visibility** (0cf537a9): the actions snapshot includes the diff
   each edit applied. Without it the verifier judged edits blind — it
   false-flagged a real edit ("no smoke added" while the smoke was on disk,
   v2) and had no way to distinguish a fabricated edit from a real one.

## Rejected alternatives

- **Fail-closed on empty verdicts** — a stalling same-model verifier would
  deadlock valid completions; the retry+warn keeps fail-open honest.
- **Verify only artifact-producing turns** (upstream's effectful gate as the
  *only* trigger) — misses read-only-turn fabrications; kept as trigger but
  patched via flag semantics.
- **Bigger verifier model** — not available on this hardware as a resident
  second model; design must survive a weak judge.

## Validation

`tests/test_verifier_empty_response_retry.py`,
`tests/test_verifier_flag_dodging.py`, `tests/test_document_diff_stats.py`
(snapshot diff). Live: flagged a fabricated smoke-edit claim in the visible
chat ("UNMET: No smoke effect added") — before the diff fix that flag was
also produced *incorrectly* against a real edit; after it the verifier sees
`+`/`-` lines.

## Open items

- Verify done-claims whenever ANY tools ran, even artifact-free ones (the
  `get_workspace` specimen) — still gated on effectful tools.
- `_VERIFIER_MAX_ROUNDS = 2` cap: a persistent liar exhausts the cap and the
  final message ships with the flag visible in chat; acceptable, by design.
- Same-model verification is a structural conflict of interest; a dedicated
  small judge model is worth testing when hardware allows.

## Decision log

- 2026-08-02 — UNMET-line parsing + accountability (`_verifier_fix_pending`).
- 2026-08-03 — empty-response retry + gpt-oss effort fix (ba6522f5).
- 2026-08-04 — effectful-only flag clearing (3917a9fa); diff in snapshot (0cf537a9).
- 2026-08-04 — failed commands are LOUD in the snapshot ("!! FAILED (exit N)
  — if never addressed afterwards, this requirement is UNMET"): a weak judge
  passed a turn whose final command failed quietly ("(exit 13)" suffix) and
  was never retried. Same commit: subprocess output is ANSI-stripped before
  reaching model context/UI, and the bash tool descriptions state no TTY is
  attached (interactive wizards fail; use --yes/--defaults).
