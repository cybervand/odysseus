"""The supports_tools lookup must find a native Ollama endpoint's own row.

A native Ollama chat request runs against "http://host:11434/api/chat".
normalize_base strips only the "/chat", yielding "http://host:11434/api" —
but the user registers the endpoint as the bare "http://host:11434". The
lookup-key list therefore never contained the stored base_url, so the
per-endpoint supports_tools toggle silently did nothing for native Ollama:
the agent loop fell through to text-only mode with zero tool schemas
(observed live: a native endpoint with supports_tools=1 still logged
_is_api_model=False tools_sent=0).
"""
from src.agent_loop import _endpoint_lookup_keys


def test_native_ollama_chat_url_yields_bare_host_key():
    keys = _endpoint_lookup_keys("http://host.docker.internal:11434/api/chat")
    assert "http://host.docker.internal:11434" in keys


def test_native_ollama_key_list_still_contains_api_variants():
    keys = _endpoint_lookup_keys("http://192.168.1.113:11434/api/chat")
    assert "http://192.168.1.113:11434/api" in keys
    assert "http://192.168.1.113:11434" in keys


def test_openai_compat_urls_unchanged():
    keys = _endpoint_lookup_keys("http://192.168.1.113:11434/v1/chat/completions")
    # normalize_base strips /chat/completions -> .../v1 (existing behaviour)
    assert "http://192.168.1.113:11434/v1" in keys
    # and no bogus bare-host key is invented for non-native URLs
    assert "http://192.168.1.113:11434" not in keys


def test_bare_url_is_its_own_key():
    keys = _endpoint_lookup_keys("http://host:11434")
    assert "http://host:11434" in keys
