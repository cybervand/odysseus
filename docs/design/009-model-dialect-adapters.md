# 009 — Model dialect adapters: one canonical state, aliases at the boundary

**Status:** Draft — approved direction (user, 2026-08-04), not yet built

## Problem

Model-family differences are handled by scattered special cases: harmony
tool-name aliases in llm_core, `_supports_thinking` think:false for
qwen/gemma, `reasoning_effort` for gpt-oss and mistral, the qwen fenced
dialect parser, and a reasoning channel that arrives as `reasoning`
(Ollama) or `reasoning_content` (llama.cpp) and is displayed/echoed
inconsistently ("Thinking…" panels that never fill; harmony echo-back
degraded). Every new model adds more `if "family" in model` branches.

## Decision (to build)

Generalize the harmony-alias pattern (doc 001) into a **dialect registry**:
Odysseus speaks ONE canonical internal contract — canonical tool names,
`reasoning` as THE thinking field, one thinking-control abstraction, one
tool-call shape — and each model family gets a declarative profile applied
symmetrically at exactly two chokepoints (outbound payload builders,
inbound stream accumulator):

```python
DIALECTS = {
  "harmony":  Dialect(match="gpt-oss", tool_aliases={"python": "run_python_code", ...},
                      thinking=("reasoning_effort", "low"), reasoning_in=("reasoning",),
                      reasoning_echo="reasoning"),
  "qwen":     Dialect(match="qwen", thinking=("think", False),
                      tool_call_repair="qwen_fenced_dialect"),
  "llamacpp": Dialect(reasoning_in=("reasoning_content", "reasoning"), ...),
}
```

- Inbound: whatever field the backend uses for thinking normalizes to
  canonical `reasoning` (fixes the sometimes-empty thinking panel and the
  echo-back mismatch in one move). Tool names un-alias; dialect argument
  quirks repair.
- Outbound: canonical state renders into the model's dialect — aliases,
  thinking controls, echo-back field name.
- `[agent-policy]` logs `dialect=harmony` per turn (doc 008 integration).
- Existing scattered branches migrate INTO profiles; no behavior change
  per family, one place to read.

## Why this is right (evidence)

Doc 001's alias fix took gpt-oss from 1/10 to 20/20 without touching
anything outside the boundary. The reasoning-field mismatch and the qwen
parser are the same disease shape; they deserve the same cure, once,
declaratively.

## Scaling: thousands of models, a dozen dialects

(User, 2026-08-04: "we aren't just building this for gpt-oss — there are
thousands of models from all over the world.") Three consequences:

1. **The dialect key is not the model name.** Thousands of models are
   finetunes of a few dozen base families served by a handful of inference
   servers; conventions come from (family chat-template × backend server).
   Profiles match on family patterns + backend, not model ids. Expect
   ~10-20 dialects covering nearly everything: harmony, qwen, deepseek-r1
   (<think> tags), glm, kimi, llama, mistral, gemma, plus backend variants
   (ollama vs llama.cpp vs vllm field names).
2. **Detect, don't enumerate.** For unknown models, PROBE once: send a
   canary request (one trivial tool + a question), observe which fields
   come back (reasoning vs reasoning_content vs inline <think>), whether
   the tool call parses, argument format. Auto-derive a profile, cache it
   per (model, endpoint), log `dialect=auto-detected:...`. Manual profiles
   become overrides, not prerequisites.
3. **Profiles are data, not code** — a JSON/YAML registry users can extend
   and share. A new model from anywhere becomes a pasted profile or one
   auto-probe, never a code change. (Also the most upstream-PR-able shape:
   the community maintains the registry.)

## Open items

- Inventory pass: grep llm_core/agent_loop for every model-name branch;
  each becomes a profile field or dies.
- Reasoning capture observability: `[agent-thinking] captured=N` per round
  so a silent field drop reads as captured=0.

## Decision log

- 2026-08-04 — drafted; user's directive: "one main state, alias for
  different models — like we did with the harmony tool."
