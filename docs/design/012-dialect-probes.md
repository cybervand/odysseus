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
