"""The observe scope: read-only live-run observation for API tokens.

Tokens never inherit admin (require_user rejects them outright), so
watching agent runs through /api/chat/runs + /api/chat/resume needs an
explicit scope — granted in the token UI, honored only when the token's
owner is an admin/single user.
"""
from routes.api_token_routes import ALLOWED_SCOPES, _normalize_scopes


def test_observe_is_an_allowed_scope():
    assert "observe" in ALLOWED_SCOPES


def test_normalize_keeps_observe():
    assert "observe" in _normalize_scopes(["observe", "chat"])


def test_unknown_scopes_still_rejected():
    import pytest
    from fastapi import HTTPException
    try:
        scopes = _normalize_scopes(["definitely-not-a-scope"])
    except HTTPException:
        return  # rejected loudly — fine
    except ValueError:
        return
    assert "definitely-not-a-scope" not in scopes  # or silently dropped
