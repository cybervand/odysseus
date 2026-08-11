"""Per-round checkpoints of in-flight assistant responses (doc 013).

Assistant messages persisted ONLY at run end: any kill (deploy, crash,
docker rm) vaporized everything the user had watched stream — refresh
became time travel to the last persisted row (2026-08-06, an entire
multi-round build reply lost). The agent loop now checkpoints the
accumulated text after every round; a surviving checkpoint after the run
is dead gets PROMOTED into a real history row on the next history load;
legitimate persistence clears it (session_manager.add_message hook).

Files, not DB rows, on purpose: a checkpoint must survive anything short
of disk loss, including the process dying mid-write elsewhere. Writes
are atomic (tmp + replace).
"""
import json
import logging
import os
import time

from src.constants import DATA_DIR

logger = logging.getLogger(__name__)

_DIR = os.path.join(DATA_DIR, "partials")


def _path(session_id: str) -> str:
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(_DIR, f"{safe}.json")


def write_partial(session_id: str, text: str, round_num: int) -> None:
    if not session_id or not text:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        tmp = _path(session_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"text": text, "round": round_num, "ts": time.time()}, f)
        os.replace(tmp, _path(session_id))
    except OSError as e:
        logger.warning("[checkpoint] write failed for %s: %s", session_id, e)


def read_partial(session_id: str):
    try:
        with open(_path(session_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def clear_partial(session_id: str) -> None:
    try:
        os.remove(_path(session_id))
    except OSError:
        pass


def promote_if_orphaned(session_id: str, session_manager, run_status) -> bool:
    """A checkpoint that survives while its run is NOT running is orphaned
    content the user watched but the DB never got — turn it into a real
    assistant row (which clears the checkpoint via the add_message hook).
    Returns True when something was promoted."""
    if run_status == "running":
        return False
    data = read_partial(session_id)
    if not data or not data.get("text"):
        return False
    # A checkpoint can outlive a run that saved its reply: late agent
    # rounds write a checkpoint after the save hook cleared it. If the
    # last assistant row already holds this content, the checkpoint is
    # stale. Promotion of a stale checkpoint made a twin message
    # (seen 2026-08-12). Clear it and do not promote.
    try:
        sess = session_manager.get_session(session_id)
        hist = getattr(sess, "history", None) or []
        last = next((m for m in reversed(hist)
                     if getattr(m, "role", "") == "assistant"), None)
        if last is not None:
            def _norm(s):
                return " ".join(str(s or "").split())
            saved = _norm(getattr(last, "content", ""))
            ckpt = _norm(data["text"])
            if saved and ckpt and (saved[-300:] in ckpt or ckpt[-300:] in saved):
                clear_partial(session_id)
                logger.info(
                    "[checkpoint] stale checkpoint matches the saved reply "
                    "for %s — cleared, not promoted", session_id)
                return False
    except Exception:
        pass
    try:
        from core.models import ChatMessage
        # Checkpoint text is the joined round_texts — post reasoning-merge,
        # each round carries its own <think> block. Saving it raw shipped
        # 32KB/16-block rows that broke display AND re-entered the model's
        # next-turn context verbatim (doc 016). Extract thinking to metadata
        # first; a reasoning-only checkpoint stays raw (extractor contract).
        from routes.chat_helpers import clean_thinking_for_save
        reply, md = clean_thinking_for_save(
            data["text"],
            {"recovered_partial": True, "rounds": data.get("round")},
        )
        session_manager.add_message(session_id, ChatMessage(
            "assistant",
            (reply or data["text"]) + "\n\n*[recovered — the run was interrupted before finishing; "
                                      "this is everything it produced]*",
            metadata=md,
        ))
        logger.info("[checkpoint] promoted orphaned partial for %s (%d chars, round %s)",
                    session_id, len(data["text"]), data.get("round"))
        return True
    except Exception as e:
        logger.warning("[checkpoint] promote failed for %s: %s", session_id, e)
        return False
