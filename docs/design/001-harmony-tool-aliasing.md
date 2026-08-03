# 001 — gpt-oss harmony tool-name aliasing

**Status:** Shipped (4dcb28f2); upstream issue #5877 / PR #5878

## Problem

gpt-oss (harmony format) ships built-in tools named `python` and `browser`,
trained to be called with **raw code as the argument**. Odysseus's agent
tools are also named `python`/`bash` but expect JSON arguments. Seeing the
name it knows, the model answers in built-in convention; Ollama's parser
dies on the raw-code arguments — HTTP 500 non-streaming
(`error parsing tool call: raw='import sys, ...'`), **silent stream
truncation** when streaming (no `[DONE]`, no error frame). To Odysseus that
is indistinguishable from a model stall: `0 chars, 0 native calls`.

Evidence: ~100 runs of a fixed multi-step prompt pinned at 0–3/10 tool-call
success; 74 HTTP 500s in Ollama's log with zero surfaced in Odysseus;
direct-to-Ollama rename ladder (12 runs/arm): names as-is **2/12**, `python`
renamed **10/12**, both renamed **12/12**. The model self-diagnosed in its
reasoning channel ("built-in 'python' function ... did cause syntax error")
hours before the experiments found it — see Lessons.

## Decision

Transport-layer alias, gated to gpt-oss only. `src/llm_core.py`:
`_HARMONY_TOOL_ALIASES` (`python`→`run_python_code`, `bash`→
`run_shell_command`, `browser`→`web_browser_tool`); `_alias_harmony_tools`
rewrites a **copy** of the outbound tool schema at both payload builders
(OpenAI-compat path and `_build_ollama_payload`); `_unalias_harmony_tool_name`
maps names back the moment a tool call arrives. Nothing inside Odysseus is
renamed — executor, logs, UI, and every other model see only the real names
(non-gpt-oss models receive the identical list object, asserted in tests).

## Rejected alternatives

- **Rename the tools across Odysseus** — churns every consumer of the tool
  names for one model family's quirk.
- **Additive alias (offer both names)** — useless: the *presence* of the
  name `python` in the schema is what arms the built-in convention.
- **Prompt-level fixes** — 68-run prompt-shape study moved success 0→~30%
  at best; the parse failure is below the prompt layer.
- **Reasoning-effort tuning** — partial mitigation only (different sampling
  → more often well-formed args); kept separately as de325b50, but not a fix.

## Validation

`tests/test_harmony_tool_aliasing.py` (7 tests). End-to-end, same killer
prompt: before 1/10 runs with any tool call → after 10/10 (plus 5/5, 5/5 in
later completion-measured series — 20/20 lifetime post-fix). qwen3-coder
5-run regression: zero interference.

## Open items

- Ollama upstream bug report (silent stream truncation on tool-call parse
  failure) — drafted intent, not filed.
- Odysseus should detect a truncated stream (no `[DONE]`) and surface it as
  an error instead of an empty round — not built.

## Lessons

When a reasoning model "stalls," **read its thinking channel first** — it
often narrates the exact failure. Would have saved ~130 experimental runs.

## Decision log

- 2026-08-02 — shipped 4dcb28f2; deployed; upstream #5877/#5878 filed.
