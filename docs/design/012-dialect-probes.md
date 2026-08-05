# 012 — Dialect probes and repair patterns

**Status:** Living document — started 2026-08-04 from gauntlet evidence

## Method (the loop that fixed llama3.1 same-day)

1. **Probe**: minimal controlled tasks per model — (a) one bash command,
   (b) one write_file with known content, (c) a two-step sequence — via the
   authenticated API. Small tasks isolate the EMISSION FORMAT from
   competence.
2. **Specimen**: pull the raw assistant content from chat_messages — the
   dialect verbatim, not a paraphrase. Specimens become test fixtures.
3. **Pattern**: add a parser to tool_parsing's dialect chain (3c qwen-XML,
   3d llama-JSON, ...) with the specimen as its test.
4. **Rematch**: rerun the gauntlet tier for that model. Zero → pass is the
   only accepted proof.

## Taxonomy from gauntlet runs 1-3 (2026-08-04)

| Dialect | Models | Emission | Status |
|---|---|---|---|
| llama3-JSON | llama3.1 | bare {"name","parameters"} in text | FIXED (3d, 902dc787) — rematch PASS |
| fenced-bash | deepseek-r1, hermes3 | ```bash fences (+ heredocs), past-tense claims | designed: fenced-fallback (guarded skip_fenced=False when 0 native calls) |
| bare-invocation | glm4 | tool name line + shell-quoted args, no markup | pattern 3e candidate — probing now |
| pythonic | llama3.2 | [func(args)] python list (vLLM: pythonic) | pattern queued |
| planner pathology | mistral-nemo, command-r7b | markdown plans / prose, no calls | NOT a parser fix — needs plan-then-execute loop (day-one gpt-oss design, doc 002-adjacent) |
| silent death | phi4 | empty response with tools attached | needs Ollama-side trace before naming |

## Probe protocol

Per model: session via API token; prompts:
- P1: "Use your bash tool to run exactly: echo dialect-probe-1"
- P2: "Use write_file to create probe.txt containing exactly: hello-dialect"
- P3: "Run bash: mkdir -p probe_dir — then write_file probe_dir/a.txt with content: two-step"
Collect raw content + tool_events; grade: native call? parsed by which
pattern? raw markup shape?

## Results log

- 2026-08-04 — probes launched: deepseek-r1:14b, glm4:9b.
- 2026-08-04 — GLM arc, three rematches in one night:
  1. Pattern 3e (bare invocation) → 0→8 real bash round-trips; writes
     dropped (second arg shape) → model spent 7 rounds debugging the void.
  2. Paren-call variant added → first real file (index.html, 1889B); then
     wrote one file and narrated the rest (fabrication persists).
  3. **Turn-taking note experiment: REGRESSION.** Abstract protocol
     instruction changed its emission shape (bare → generic fences, both
     unparseable) and drove it to create_document (document-world escape).
     Rolled back same night. LESSON: text dialects are prompt-sensitive —
     protocol notes must FEW-SHOT the exact expected format, never
     describe it abstractly. Note disabled pending v2 with examples.
  - GLM status: dialect parsing DONE (both shapes); remaining =
    fabrication/persistence → verifier-driven continuation +
    plan-then-execute, with a format-example note as v2.
- 2026-08-05 — GLM campaign closed at rematch 8 (stopping rule). Final:
  - Shipped along the way, all models benefit: v2 few-shot turn-note
    (fixed turn-taking — zero fabricated outputs from rematch 5 on),
    colon-inline + generalized write parser (SIX serialization shapes,
    one branch), verifier micro-step driver (commands the first flagged
    item as the exact next call; creation-type flags lead, verification
    last — the day-one gpt-oss "third key", finally built).
  - Best run: real index.html 2535B + honest incompleteness report.
    Worst run (same build!): 14 calls of pure mkdir/ls anxiety, zero
    writes emitted.
  - VERDICT: harness deterministic, model stochastic. glm4:9b =
    single-file capable, multi-file unreliable at 9B — per-run behavior
    variance dominates. Not a parser problem anymore. Revisit with a
    larger GLM or a stronger judge; every fix built for it stays and
    serves the fleet.
- 2026-08-05 — deepseek-r1 arc (fenced-fallback campaign):
  1. Fenced fallback shipped (fencedfb): rematch 1 = dir yes, 10 tools,
     0 files. First real deepseek directory EVER. Autopsy: ONE bash fence
     interleaving mkdir with `write_file <path> -- <<EOL` pseudo-commands
     (exit 127 as shell); model correctly diagnosed its own failure for 7
     rounds, then fled to create_document.
  2. Heredoc splitter shipped (fencedfb2): rematch 2 = dir yes, 16 tools,
     0 files — splitter unexercised: the model emitted NO heredocs this
     run, improvised create_document in round 1 instead. Serialization
     roulette confirmed.
  3. RESEARCH (the missing piece): R1 distills were never trained on
     function calling (0528 refresh never reached the 14b registry tag),
     and the Ollama registry template renders tool CALLS (DSML tokens)
     but never the tool DEFINITIONS — the model NEVER SEES THE SCHEMAS
     (ollama#8517, #10935, #11131). Its only tool knowledge is our prose
     system prompt → per-run improvisation is the expected outcome, not a
     quirk. Community-proven anchor (MFDoom template): bare-JSON
     {name, parameters} — exactly Pattern 3d, parsed in the PRIMARY pass.
  4. Few-shot bare-JSON turn-note shipped (fencedfb3). Rematch 3 CSV said
     1 file; rematch 4 CSV said 0.
  5. **MEASUREMENT BUG FOUND — graded verdicts were wrong.** The rematch
     scripts grade at the 420s stream cut, but buffered runs OUTLIVE the
     disconnect: rematch 3's run kept working ~13 min past the cut and
     FINISHED THE JOB — 3/3 real files on disk (index.html 2857B,
     styles.css 1759B, app.js 589B), via THREE write idioms (bare-JSON
     write_file, cat-heredocs, split write_file-heredocs). Rematch 4 had
     1+ file and was still writing when checked. GLM dirs re-checked:
     unchanged — GLM genuinely stops; its plateau verdict stands. The bug
     specifically penalizes slow reasoners that keep working. Fix:
     rematch scripts now drain /api/chat/runs (up to 15 min) before
     grading. Tier-1 caveat: any slow thinking model's gauntlet numbers
     from before this fix are lower bounds.
  6. deepseek-r1:14b REAL status: full task completion with the complete
     stack (fenced fallback + heredoc splitter + bare-JSON note +
     micro-step driver) — just slower than the old observation window.
  7. **CONTAMINATION + LINGERING RUNS.** At 21:4x all three rematch runs
     (3/4/5) were STILL alive concurrently — rematch 3 at 31k events,
     rewriting its (already complete) files at 21:34. Sequential tests
     were never sequential: rematch 4 competed with 3's leftover run;
     rematch 5 was fully starved (no dir, invalid sample). Cleared via
     container restart. Protocol now: pre-flight assert /api/chat/runs
     EMPTY before launch + drain before grading (both in rematch script).
     Sample tally for the note build: rematch 3 = clean FULL PASS 3/3;
     rematch 4/5 = contaminated, void. Clean rematch 6 launched.
     OPEN QUESTION: does the agent-timeout setting bound buffered-run
     wall clock? A finished-then-still-working run suggests the loop
     lacks a "done means stop" guard — upstream also plans a runaway
     detector (#3266 submodule); convergent need, candidate next fix.
  8. **VERDICT — deepseek-r1:14b: tier-1 PASS.** Clean rematch 6 under
     the full protocol (preflight empty + drain): 3/3 files (3541/394/540
     bytes), 47 calls, 0 dialect fails. Clean-sample record for the
     bare-JSON note build: 2/2 full passes (rematches 3 and 6). From
     zero real actions ever to reliable completion in one day: fenced
     fallback → heredoc splitter → bare-JSON few-shot note (research-
     informed) → drain-aware grading. Lingering-run bug REPRODUCED on
     rematch 6 (22k events, still executing after task completion;
     cleared by restart) — termination guard is now the top fix.
- 2026-08-05 — REGISTRY: src/dialect_profiles.py is now THE index (doc
  009 "profiles as data" delivered). Turn notes, fenced-fallback flags,
  pattern assignments, and diagnosed-only families all live in one
  declarative table; agent_loop consumes it; tests enforce that every
  note's examples parse through our own chain and diagnosed rows carry
  no runtime behavior.
