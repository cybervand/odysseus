"""Doc 016: the project ledger — parse/render, the evidence gate, merge
rules, mechanical failure lines, storage, and the updater end-to-end.

The trust rules under test are the doc's core: evidence ticks boxes,
claims never; prior items never vanish; done never silently un-ticks;
countables itemize; a failing last command shouts.
"""
import asyncio
import json

import pytest

from src.feed_log import EphemeralEventLog
from src.project_ledger import (
    LEDGER_KIND, _enforce, _has_anchor, ledger_context_message, load_ledger,
    parse_ledger_text, render_ledger, save_ledger, update_ledger,
)

EFFECTFUL = frozenset({"bash", "python", "write_file"})

SNAPSHOT = (
    "[bash] mkdir skilodge\n-> (no output)\n\n"
    "[write_file] skilodge/app.py\n-> wrote 88 lines\n\n"
    "[bash] curl -o skilodge/static/img/hero.jpg https://upload.wikimedia.org/x/hero.jpg\n-> saved 214KB"
)


def _item(text, status="open", evidence="", subitems=None):
    return {"text": text, "status": status, "evidence": evidence,
            "subitems": subitems or []}


def _ledger(*items):
    return {"version": 1, "updated_ts": 0.0, "items": list(items)}


class TestParseRender:
    def test_round_trip_with_subitems_and_failure(self):
        text = (
            "[x] create skilodge folder | evidence: mkdir skilodge\n"
            "[~] download images\n"
            "    [x] hero.jpg | evidence: skilodge/static/img/hero.jpg\n"
            "    [ ] spa.jpg | known: https://example.org/spa.jpg\n"
            "[ ] frontend templates\n"
            "!! npm run build exited 1 - unaddressed"
        )
        led = parse_ledger_text(text)
        assert [i["status"] for i in led["items"]] == ["done", "partial", "open", "failed"]
        subs = led["items"][1]["subitems"]
        assert subs[0]["status"] == "done" and "hero.jpg" in subs[0]["evidence"]
        assert subs[1]["status"] == "open" and "spa.jpg" in subs[1]["evidence"]
        rendered = render_ledger(led)
        assert "[~] download images (1/2)" in rendered
        assert "    [x] hero.jpg" in rendered
        assert "!! npm run build exited 1" in rendered

    def test_fenced_output_and_counter_stripping(self):
        led = parse_ledger_text("```\n[x] a thing (3/5) | evidence: skilodge/app.py\n```")
        assert led["items"][0]["text"] == "a thing"

    def test_garbage_returns_none(self):
        assert parse_ledger_text("I could not determine the ledger.") is None
        assert parse_ledger_text("") is None


class TestEvidenceGate:
    def test_anchor_path_token(self):
        assert _has_anchor("wrote skilodge/app.py", SNAPSHOT)
        assert _has_anchor("evidence: hero.jpg saved", SNAPSHOT)

    def test_no_anchor_generic_words(self):
        assert not _has_anchor("completed successfully", SNAPSHOT)
        assert not _has_anchor("", SNAPSHOT)

    def test_tick_without_anchor_rejected(self):
        prior = _ledger(_item("write the backend"))
        proposed = _ledger(_item("write the backend", "done", "it is finished now"))
        out = _enforce(prior, proposed, SNAPSHOT, [], EFFECTFUL)
        assert out["items"][0]["status"] == "open"
        assert out["items"][0]["evidence"].startswith("unverified:")

    def test_tick_with_anchor_accepted(self):
        prior = _ledger(_item("write the backend"))
        proposed = _ledger(_item("write the backend", "done", "wrote skilodge/app.py"))
        out = _enforce(prior, proposed, SNAPSHOT, [], EFFECTFUL)
        assert out["items"][0]["status"] == "done"

    def test_new_item_tick_needs_anchor_too(self):
        proposed = _ledger(_item("magic step", "done", "trust me"))
        out = _enforce(None, proposed, SNAPSHOT, [], EFFECTFUL)
        assert out["items"][0]["status"] == "open"

    def test_subitem_tick_gated_and_parent_derives(self):
        prior = _ledger(_item("download images", subitems=[
            {"text": "hero.jpg", "status": "open", "evidence": ""},
            {"text": "spa.jpg", "status": "open", "evidence": ""},
        ]))
        proposed = _ledger(_item("download images", "done", "", subitems=[
            {"text": "hero.jpg", "status": "done", "evidence": "skilodge/static/img/hero.jpg"},
            {"text": "spa.jpg", "status": "done", "evidence": "definitely downloaded"},
        ]))
        out = _enforce(prior, proposed, SNAPSHOT, [], EFFECTFUL)
        subs = out["items"][0]["subitems"]
        assert subs[0]["status"] == "done"
        assert subs[1]["status"] == "open"          # no anchor -> rejected
        assert out["items"][0]["status"] == "partial"


class TestMergeRules:
    def test_dropped_prior_item_survives(self):
        prior = _ledger(_item("keep me", "done", "skilodge/app.py"),
                        _item("still open"))
        proposed = _ledger(_item("brand new requirement"))
        out = _enforce(prior, proposed, SNAPSHOT, [], EFFECTFUL)
        texts = [i["text"] for i in out["items"]]
        assert "keep me" in texts and "still open" in texts and "brand new requirement" in texts
        kept = next(i for i in out["items"] if i["text"] == "keep me")
        assert kept["status"] == "done"

    def test_done_never_unticks_silently(self):
        prior = _ledger(_item("finished thing", "done", "skilodge/app.py"))
        proposed = _ledger(_item("finished thing", "open"))
        out = _enforce(prior, proposed, SNAPSHOT, [], EFFECTFUL)
        assert out["items"][0]["status"] == "done"
        assert out["items"][0]["evidence"] == "skilodge/app.py"

    def test_done_to_failed_needs_anchor(self):
        prior = _ledger(_item("finished thing", "done", "skilodge/app.py"))
        bare = _ledger(_item("finished thing", "failed", "it broke"))
        out = _enforce(prior, bare, SNAPSHOT, [], EFFECTFUL)
        assert out["items"][0]["status"] == "done"

    def test_mechanical_failure_line_for_last_effectful(self):
        events = [
            {"tool": "write_file", "command": "skilodge/app.py", "exit_code": 0},
            {"tool": "bash", "command": "python3 skilodge/app.py", "exit_code": 1},
        ]
        out = _enforce(None, _ledger(_item("run the app")), SNAPSHOT, events, EFFECTFUL)
        failed = [i for i in out["items"] if i["status"] == "failed"]
        assert len(failed) == 1
        assert "python3 skilodge/app.py" in failed[0]["text"]
        assert "exited 1" in failed[0]["text"]

    def test_no_failure_line_when_last_effectful_ok(self):
        events = [{"tool": "bash", "command": "ls", "exit_code": 1},
                  {"tool": "bash", "command": "python3 app.py", "exit_code": 0}]
        out = _enforce(None, _ledger(_item("x")), SNAPSHOT, events, EFFECTFUL)
        assert not [i for i in out["items"] if i["status"] == "failed"]


class TestStorageAndInjection:
    def test_latest_wins_round_trip(self):
        log = EphemeralEventLog()
        save_ledger("s1", _ledger(_item("v1 item")), log=log)
        save_ledger("s1", _ledger(_item("v2 item", "done", "skilodge/app.py")), log=log)
        led = load_ledger("s1", log=log)
        assert led["items"][0]["text"] == "v2 item"

    def test_context_message_shape(self):
        log = EphemeralEventLog()
        save_ledger("s2", _ledger(
            _item("write backend", "done", "skilodge/app.py"),
            _item("frontend"),
        ), log=log)
        msg = ledger_context_message("s2", log=log)
        assert msg["role"] == "system"
        assert "do not repeat them" in msg["content"]
        assert "[x] write backend | skilodge/app.py" in msg["content"]
        assert "[ ] frontend" in msg["content"]

    def test_no_ledger_no_message(self):
        assert ledger_context_message("nope", log=EphemeralEventLog()) is None


class TestUpdaterEndToEnd:
    def test_update_ledger_full_cycle(self, monkeypatch):
        import src.llm_core

        async def fake_llm(**kwargs):
            return (
                "[x] create skilodge folder | evidence: mkdir skilodge\n"
                "[x] write backend | evidence: skilodge/app.py\n"
                "[ ] frontend templates\n"
                "[x] fake claim | evidence: nothing real happened"
            )

        monkeypatch.setattr(src.llm_core, "llm_call_async", fake_llm)
        log = EphemeralEventLog()
        events = [{"tool": "bash", "command": "mkdir skilodge", "exit_code": 0},
                  {"tool": "write_file", "command": "skilodge/app.py", "exit_code": 0}]
        led = asyncio.run(update_ledger(
            "s3", "build a lodge site", events, SNAPSHOT,
            endpoint_url="http://x", model="m", headers={},
            effectful_tools=EFFECTFUL, log=log,
        ))
        by_text = {i["text"]: i for i in led["items"]}
        assert by_text["create skilodge folder"]["status"] == "done"
        assert by_text["write backend"]["status"] == "done"
        assert by_text["frontend templates"]["status"] == "open"
        assert by_text["fake claim"]["status"] == "open"     # anchor gate
        # persisted latest-wins
        assert load_ledger("s3", log=log)["items"] == led["items"]

    def test_unparseable_updater_keeps_prior(self, monkeypatch):
        import src.llm_core

        async def fake_llm(**kwargs):
            return "Sorry, I cannot help with that."

        monkeypatch.setattr(src.llm_core, "llm_call_async", fake_llm)
        log = EphemeralEventLog()
        save_ledger("s4", _ledger(_item("survives", "done", "skilodge/app.py")), log=log)
        out = asyncio.run(update_ledger(
            "s4", "req", [], SNAPSHOT,
            endpoint_url="http://x", model="m", headers={},
            effectful_tools=EFFECTFUL, log=log,
        ))
        assert out is None
        assert load_ledger("s4", log=log)["items"][0]["text"] == "survives"
