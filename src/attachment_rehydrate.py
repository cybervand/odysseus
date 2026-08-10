"""Rehydrate persisted image attachments into history messages at LLM-call time.

Upstream #5420 (carried by this fork) flattens multimodal chat content to
text plus attachment-ref lines before DB persistence — deliberately keeping
base64 out of storage. The regression that ships with it (upstream #5499 /
#4723 family, reproduced here 2026-08-10 on the imgtest container): once a
session reloads from the DB, a vision model receives only the flattened
text, and instead of admitting it cannot see the image it HALLUCINATES one
from the filename ("shapes-test.png" → invented shapes, all wrong).

The upload files persist on the data volume, and every stored message that
carried attachments still lists them in ``metadata.attachments``. So at
call-assembly time — for vision-capable models only — walk recent history
user messages whose metadata lists image attachments but whose content is a
bare string (the flattened form), re-resolve each upload owner-checked, and
rebuild a multimodal content list. Storage stays lean (#5420's goal); the
model regains its eyes.

Bounded: at most ``max_images`` most-recent images and ``max_bytes`` total
raw file bytes per call; older images stay flattened (their ref lines still
name them, so the model can ask the user to re-attach).
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

REHYDRATE_MAX_IMAGES = 4
REHYDRATE_MAX_BYTES = 8_000_000

# The stored flat form contains "[N inline media payload(s) omitted]" from
# attachment_refs._text_from_blocks — false once the image is re-attached.
_OMITTED_LINE_RE = re.compile(r"\[\d+ inline media payloads? omitted\]\n?")


def _confined(upload_handler, path: str) -> bool:
    if hasattr(upload_handler, "_inside_upload_dir"):
        return bool(upload_handler._inside_upload_dir(path))
    if hasattr(upload_handler, "inside_base_dir"):
        return bool(upload_handler.inside_base_dir(path))
    return False


def _image_block(info: Dict[str, Any], path: str) -> Dict[str, Any] | None:
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.warning("rehydrate: failed to read %s: %s", path, e)
        return None
    ext = os.path.splitext(path.lower())[1][1:]
    mime = str(info.get("mime") or "")
    image_format = ext or (mime.split("/", 1)[1] if mime.startswith("image/") else "png")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/{image_format};base64,{encoded}"},
    }


def rehydrate_history_images(
    messages: List[Any],
    upload_handler,
    owner: str | None = None,
    max_images: int = REHYDRATE_MAX_IMAGES,
    max_bytes: int = REHYDRATE_MAX_BYTES,
) -> int:
    """Rebuild flattened user messages that referenced image uploads.

    Mutates ``messages`` in place (the per-call ``to_dict()`` copies — never
    the session's ChatMessage objects). Returns the number of images
    re-attached. Callers gate on the model being vision-capable.
    """
    budget_images = max_images
    budget_bytes = max_bytes
    rehydrated = 0

    for msg in reversed(messages):
        if budget_images <= 0 or budget_bytes <= 0:
            break
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue  # live multimodal turn, or something we don't own
        atts = (msg.get("metadata") or {}).get("attachments") or []
        image_atts = [
            a for a in atts
            if isinstance(a, dict) and str(a.get("mime", "")).startswith("image/")
        ]
        if not image_atts:
            continue

        blocks: List[Dict[str, Any]] = []
        for att in image_atts:
            if budget_images <= 0 or budget_bytes <= 0:
                break
            fid = str(att.get("id") or "").strip()
            if not fid:
                continue
            info = upload_handler.resolve_upload(fid, owner=owner)
            if not info:
                logger.info("rehydrate: attachment %s not found/authorized", fid)
                continue
            path = info.get("path")
            if not path or not os.path.exists(path) or not _confined(upload_handler, path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > budget_bytes:
                continue
            block = _image_block(info, path)
            if block is None:
                continue
            blocks.append(block)
            budget_images -= 1
            budget_bytes -= size
            rehydrated += 1

        if blocks:
            text = _OMITTED_LINE_RE.sub("", content).strip()
            msg["content"] = [{"type": "text", "text": text}] + blocks

    if rehydrated:
        logger.info("rehydrated %d history image(s) for vision model call", rehydrated)
    return rehydrated
