"""Tripwire tests for doc 021 phase 2: fork code stays in fork files.

Fork features that live inline in upstream files cause cherry-pick
conflicts with each upstream patch to those files. The extraction
moved the feature bodies to static/js/fork/ and static/css/fork.css.
These tests make sure the bodies do not come back.
"""

from pathlib import Path

APP_JS = Path("static/app.js").read_text(encoding="utf-8")
STYLE_CSS = Path("static/style.css").read_text(encoding="utf-8")


def test_command_menu_body_lives_in_fork_module():
    fork = Path("static/js/fork/commandMenu.js").read_text(encoding="utf-8")
    assert "cmd-think-check" in fork
    assert "cmd-verifier-check" in fork
    assert "cmd-effort-stepper" in fork


def test_camera_body_lives_in_fork_module():
    fork = Path("static/js/fork/camera.js").read_text(encoding="utf-8")
    assert "camera-input" in fork
    assert "overflow-camera-btn" in fork


def test_app_js_keeps_only_the_hooks():
    """app.js may import and start the fork modules. The bodies must
    not be in app.js. Inline bodies there collide with upstream
    patches."""
    assert "js/fork/commandMenu.js" in APP_JS
    assert "js/fork/camera.js" in APP_JS
    for marker in ("cmd-think-check", "cmd-verifier-check",
                   "cmd-effort-stepper", "camera-input"):
        assert marker not in APP_JS, (
            f"fork marker {marker!r} is back inside app.js — move the "
            "code to static/js/fork/ (doc 021, phase 2)"
        )


def test_fork_css_lives_in_fork_file():
    fork = Path("static/css/fork.css").read_text(encoding="utf-8")
    assert ".cmd-menu" in fork
    assert ".cmd-stepper" in fork
    for marker in (".cmd-menu", ".cmd-stepper", ".cmd-step ", ".cmd-pill"):
        assert marker not in STYLE_CSS, (
            f"fork CSS {marker!r} is back inside style.css — move the "
            "rules to static/css/fork.css (doc 021, phase 2)"
        )


def test_page_links_the_fork_stylesheet():
    html = Path("static/index.html").read_text(encoding="utf-8")
    assert "/static/css/fork.css" in html


def test_service_worker_precaches_fork_files():
    sw = Path("static/sw.js").read_text(encoding="utf-8")
    for path in ("/static/css/fork.css",
                 "/static/js/fork/commandMenu.js",
                 "/static/js/fork/camera.js"):
        assert path in sw
