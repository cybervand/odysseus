"""Unit tests for src/attachment_rehydrate.py — the fork fix for upstream
#5499/#4723 (vision models hallucinating reloaded images, root cause #5420).

The live repro (2026-08-10, imgtest container): turn 1 attaches shapes-test.png
and the model answers "OK"; after a container restart the reloaded session
carries only flattened text, and gemma4 invented an entirely fictional image
from the filename. Rehydration re-attaches the persisted upload at
call-assembly time for vision models.
"""

import base64
import os

import pytest

from src.attachment_rehydrate import rehydrate_history_images


class FakeUploadHandler:
    def __init__(self, files, confined=True):
        self.files = files
        self.confined = confined
        self.resolve_calls = []

    def resolve_upload(self, fid, owner=None):
        self.resolve_calls.append((fid, owner))
        return self.files.get(fid)

    def _inside_upload_dir(self, path):
        return self.confined


@pytest.fixture
def png_upload(tmp_path):
    p = tmp_path / "shapes.png"
    p.write_bytes(b"\x89PNG-fake-bytes")
    return {"path": str(p), "mime": "image/png", "name": "shapes.png"}


def _flat_msg(att_id="up1.png", mime="image/png"):
    return {
        "role": "user",
        "content": ("Reply with only the word OK.\n\n"
                    "[Image attached: shapes.png]\n"
                    "[1 inline media payload omitted]\n"
                    "[Attachment: shapes.png | id=up1.png | mime=image/png]"),
        "metadata": {"attachments": [
            {"id": att_id, "mime": mime, "name": "shapes.png"}]},
    }


def test_rehydrates_flattened_image_message(png_upload):
    handler = FakeUploadHandler({"up1.png": png_upload})
    messages = [{"role": "system", "content": "sys"}, _flat_msg()]

    n = rehydrate_history_images(messages, handler, owner="alice")

    assert n == 1
    assert handler.resolve_calls == [("up1.png", "alice")]
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert "inline media payload omitted" not in content[0]["text"]
    assert "[Attachment: shapes.png" in content[0]["text"]
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw == b"\x89PNG-fake-bytes"


def test_non_image_attachments_untouched(png_upload):
    handler = FakeUploadHandler({"up1.png": png_upload})
    msg = _flat_msg(mime="application/pdf")
    original = msg["content"]
    assert rehydrate_history_images([msg], handler) == 0
    assert msg["content"] == original


def test_live_multimodal_turn_untouched(png_upload):
    handler = FakeUploadHandler({"up1.png": png_upload})
    msg = {
        "role": "user",
        "content": [{"type": "text", "text": "hi"},
                    {"type": "image_url", "image_url": {"url": "data:..."}}],
        "metadata": {"attachments": [{"id": "up1.png", "mime": "image/png"}]},
    }
    assert rehydrate_history_images([msg], handler) == 0
    assert handler.resolve_calls == []


def test_unauthorized_upload_skipped(png_upload):
    handler = FakeUploadHandler({})  # resolve_upload returns None
    msg = _flat_msg()
    original = msg["content"]
    assert rehydrate_history_images([msg], handler, owner="mallory") == 0
    assert msg["content"] == original


def test_unconfined_path_skipped(png_upload):
    handler = FakeUploadHandler({"up1.png": png_upload}, confined=False)
    msg = _flat_msg()
    assert rehydrate_history_images([msg], handler) == 0
    assert isinstance(msg["content"], str)


def test_image_budget_prefers_most_recent(png_upload, tmp_path):
    p2 = tmp_path / "second.png"
    p2.write_bytes(b"second-image")
    handler = FakeUploadHandler({
        "up1.png": png_upload,
        "up2.png": {"path": str(p2), "mime": "image/png", "name": "second.png"},
    })
    older = _flat_msg("up1.png")
    newer = _flat_msg("up2.png")
    messages = [older, {"role": "assistant", "content": "OK"}, newer]

    n = rehydrate_history_images(messages, handler, max_images=1)

    assert n == 1
    assert isinstance(newer["content"], list)   # most recent wins
    assert isinstance(older["content"], str)    # budget exhausted


def test_byte_budget_skips_oversize(png_upload, tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"x" * 1000)
    handler = FakeUploadHandler({
        "up1.png": {"path": str(big), "mime": "image/png", "name": "big.png"}})
    msg = _flat_msg()
    assert rehydrate_history_images([msg], handler, max_bytes=100) == 0
    assert isinstance(msg["content"], str)


def test_missing_file_skipped(tmp_path):
    gone = tmp_path / "deleted.png"
    handler = FakeUploadHandler({
        "up1.png": {"path": str(gone), "mime": "image/png", "name": "gone.png"}})
    msg = _flat_msg()
    assert rehydrate_history_images([msg], handler) == 0
    assert isinstance(msg["content"], str)
