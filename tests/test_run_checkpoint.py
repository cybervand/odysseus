"""Round checkpoints: a killed run leaves its reply behind (doc 013).

An entire multi-round assistant reply was lost to a container restart —
persistence only ran at run end, so refresh time-traveled to the last
persisted row. Now every round checkpoints to disk; a checkpoint that
survives its run gets promoted into real history; a legitimate assistant
persist clears it.
"""
import src.run_checkpoint as rc


class _FakeSM:
    def __init__(self):
        self.added = []

    def add_message(self, sid, msg):
        self.added.append((sid, msg))
        rc.clear_partial(sid)  # mirrors the real add_message hook


def test_write_read_clear_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_DIR", str(tmp_path / "partials"))
    rc.write_partial("s1", "hello after round 3", 3)
    data = rc.read_partial("s1")
    assert data["text"] == "hello after round 3"
    assert data["round"] == 3
    rc.clear_partial("s1")
    assert rc.read_partial("s1") is None


def test_promote_orphaned_creates_row_and_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_DIR", str(tmp_path / "partials"))
    rc.write_partial("s2", "watched but never persisted", 5)
    sm = _FakeSM()
    assert rc.promote_if_orphaned("s2", sm, run_status="done") is True
    assert len(sm.added) == 1
    sid, msg = sm.added[0]
    assert sid == "s2"
    assert "watched but never persisted" in msg.content
    assert "recovered" in msg.content
    assert rc.read_partial("s2") is None          # hook cleared it
    # Second call: nothing left to promote.
    assert rc.promote_if_orphaned("s2", sm, run_status="done") is False


def test_no_promotion_while_running(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_DIR", str(tmp_path / "partials"))
    rc.write_partial("s3", "still streaming", 2)
    sm = _FakeSM()
    assert rc.promote_if_orphaned("s3", sm, run_status="running") is False
    assert sm.added == []
    assert rc.read_partial("s3") is not None      # untouched


def test_empty_text_never_checkpointed(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_DIR", str(tmp_path / "partials"))
    rc.write_partial("s4", "", 1)
    assert rc.read_partial("s4") is None
