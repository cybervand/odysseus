"""Write-time health checks (2026-08-08): syntax + image references.

Born from production evidence: gemma4's gear site shipped two fabricated
Unsplash URLs (both 404 — training-data leakage instead of find_images),
qwen's lodge pages carried a stray </div>, and blocked downloads saved
HTML error pages as .jpg. All deterministic to catch at write time.
Network-free: _head_ok is patched.
"""
import pytest

from src.agent_tools import write_checks
from src.agent_tools.write_checks import check_written_file


def _write(tmp_path, name, content, binary=False):
    p = tmp_path / name
    if binary:
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return str(p)


def test_python_syntax_error_caught(tmp_path):
    p = _write(tmp_path, "app.py", "def broken(:\n    pass\n")
    note = check_written_file(p)
    assert note and "python syntax error" in note


def test_valid_python_passes(tmp_path):
    p = _write(tmp_path, "app.py", "import os\nprint(os.name)\n")
    assert check_written_file(p) is None


def test_html_mismatched_close_caught(tmp_path):
    p = _write(tmp_path, "index.html",
               "<div>\n<section>\n<p>hi</p>\n</div>\n")
    note = check_written_file(p)
    assert note is not None
    assert "</div>" in note and "<section>" in note and "missing </section>" in note


def test_html_void_close_caught(tmp_path):
    p = _write(tmp_path, "x.html", "<div><img src='a.png'></img></div>")
    note = check_written_file(p)
    assert note and "void element" in note
    # (the bogus a.png also reports as missing — both problems listed)
    assert "NOT FOUND" in note


def test_jinja_constructs_no_false_positive(tmp_path):
    p = _write(tmp_path, "base.html",
               "<html><body>\n{% if x %}<div>{{ y }}</div>{% endif %}\n"
               "{# comment with <div> #}\n<script>if (a<b) {}</script>\n"
               "</body></html>\n")
    assert check_written_file(p) is None


def test_local_image_missing_caught(tmp_path):
    p = _write(tmp_path, "page.html",
               '<html><body><img src="/static/images/kitchen.jpg"></body></html>')
    note = check_written_file(p)
    assert note and "kitchen.jpg" in note and "NOT FOUND" in note


def test_local_image_found_flask_shape(tmp_path):
    (tmp_path / "static" / "images").mkdir(parents=True)
    (tmp_path / "static" / "images" / "ok.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (tmp_path / "templates").mkdir()
    p = _write(tmp_path, "templates/about.html",
               '<html><body><img src="/static/images/ok.png"></body></html>')
    assert check_written_file(p) is None


def test_fake_image_magic_bytes_caught(tmp_path):
    (tmp_path / "static").mkdir()
    # The curl-saved-error-page case: .jpg containing HTML.
    (tmp_path / "static" / "hero.jpg").write_text(
        "<html><head><title>403 Forbidden</title></head></html>")
    p = _write(tmp_path, "page.html",
               '<html><body><img src="/static/hero.jpg"></body></html>')
    note = check_written_file(p)
    assert note and "NOT an image" in note and "error page" in note


def test_remote_dead_url_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(write_checks, "_head_ok", lambda url: False)
    p = _write(tmp_path, "page.html",
               '<html><body><img src="https://images.unsplash.com/photo-152907053-fake"></body></html>')
    note = check_written_file(p)
    assert note and "not reachable" in note and "find_images" in note


def test_remote_live_url_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(write_checks, "_head_ok", lambda url: True)
    p = _write(tmp_path, "page.html",
               '<html><body><img src="https://live.staticflickr.com/x.jpg"></body></html>')
    assert check_written_file(p) is None


def test_json_and_css_checks(tmp_path):
    bad_json = _write(tmp_path, "cfg.json", '{"a": 1,}')
    assert "invalid json" in (check_written_file(bad_json) or "")
    bad_css = _write(tmp_path, "s.css", "body { color: red; \n.x { }")
    assert "unbalanced" in (check_written_file(bad_css) or "")
    ok_css = _write(tmp_path, "ok.css", "body { color: red; }")
    assert check_written_file(ok_css) is None


def test_unknown_extension_ignored(tmp_path):
    p = _write(tmp_path, "notes.txt", "<div> not html, just notes")
    assert check_written_file(p) is None
