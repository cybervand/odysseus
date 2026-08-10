"""Per-request thinking/reasoning overrides for LLM calls.

The chat-bar command menu (2026-08-11) lets the user set thinking on/off
and a reasoning-effort level per message. Those choices must reach the
payload builders buried under stream_llm's wrapper layers; threading a
parameter through every signature would touch a dozen shared functions,
so the overrides ride ContextVars set inside the SSE generator (which
runs as a detached agent_runs task — request-handler context does NOT
propagate there, so the generator itself sets and resets them).

Semantics:
- think_mode "auto": existing per-path policy (chat streams think,
  agent/tool and internal calls suppress — unchanged).
- think_mode "off": suppress thinking. Harmony models (gpt-oss) were
  never trained to run think-less and get low effort instead.
- think_mode "on": request thinking where the model supports it.
- reasoning_effort "" | low | medium | high: effort level for models
  that take one (harmony levels; Ollama native think levels).
"""

from contextvars import ContextVar

THINK_MODE: ContextVar[str] = ContextVar("odysseus_think_mode", default="auto")
REASONING_EFFORT: ContextVar[str] = ContextVar("odysseus_reasoning_effort", default="")

_EFFORTS = {"low", "medium", "high"}


def set_overrides(think_mode: str = "", reasoning_effort: str = ""):
    """Validate + set the per-request overrides. Returns reset tokens."""
    tm = (think_mode or "auto").strip().lower()
    if tm not in ("auto", "off", "on"):
        tm = "auto"
    ef = (reasoning_effort or "").strip().lower()
    if ef not in _EFFORTS:
        ef = ""
    return (THINK_MODE.set(tm), REASONING_EFFORT.set(ef))


def reset_overrides(tokens) -> None:
    try:
        THINK_MODE.reset(tokens[0])
        REASONING_EFFORT.reset(tokens[1])
    except Exception:
        pass


def _is_harmony(model: str) -> bool:
    return "gpt-oss" in (model or "").lower()


def apply_to_ollama_native(payload: dict, model: str) -> None:
    """Override `think` on a native /api/chat payload (the chat-stream
    path). Harmony models never get think=False — low effort instead."""
    tm, ef = THINK_MODE.get(), REASONING_EFFORT.get()
    if tm == "auto" and not ef:
        return
    if _is_harmony(model):
        if tm == "off":
            payload["think"] = "low"
        elif ef:
            payload["think"] = ef
    else:
        if tm == "off":
            payload["think"] = False
        elif tm == "on":
            payload.setdefault("think", True)


def effort_override() -> str:
    """Current effort override for OpenAI-compat harmony calls ('' = none)."""
    return REASONING_EFFORT.get()
