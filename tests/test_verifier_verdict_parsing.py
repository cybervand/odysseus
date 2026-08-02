"""The verifier's verdict must come from its UNMET lines, not its FAIL line.

Small local judges enumerate requirements accurately but botch the final
boolean. Both fixtures below are real verifier outputs captured live
(qwen3-coder:30b, 2026-08-01): the first marked every requirement MET and
then declared FAIL with observations ("web fetch test failed as expected",
"results.json updated correctly") as the "issues" — sending the agent off to
fix completed work. The parse must trust the enumeration over the verdict.
"""
from src.agent_loop import _parse_verifier_response


LIVE_ALL_MET_BUT_FAIL = """1. MET: Rust hello-world attempted, no tool found.
2. MET: Python benchmark executed and results saved to /app/data/bench/results.json.
3. MET: Web fetch failure handled and recorded in results.json.
4. MET: Report generated with all steps completed.

VERIFICATION: FAIL: Rust toolchain missing; benchmark in Python; web fetch test failed as expected; results.json updated correctly"""


LIVE_MIXED_WITH_REAL_UNMET = """1. MET: Rust hello-world attempted, tool missing.
2. MET: Rust benchmark written to /app/data/bench/bench.rs - UNMET (file not found).
3. MET: Python benchmark executed and results saved to /app/data/bench/results.json.
4. MET: Web fetch failure handled and recorded in results.json.

VERIFICATION: FAIL: Rust bench.rs file not created; Rust toolchain missing and not installed."""


def test_all_met_enumeration_beats_bogus_fail_verdict():
    assert _parse_verifier_response(LIVE_ALL_MET_BUT_FAIL) == []


def test_unmet_line_is_reported_even_when_prefixed_met():
    failures = _parse_verifier_response(LIVE_MIXED_WITH_REAL_UNMET)
    assert len(failures) == 1
    assert "bench.rs" in failures[0]
    assert "UNMET" in failures[0]


def test_clean_pass():
    raw = "1. MET: file written.\n2. MET: script ran.\n\nVERIFICATION: SUCCESS"
    assert _parse_verifier_response(raw) == []


def test_no_enumeration_falls_back_to_fail_verdict():
    raw = "The work is incomplete.\nVERIFICATION: FAIL: report never produced; script not run"
    assert _parse_verifier_response(raw) == [
        "report never produced", "script not run",
    ]


def test_no_enumeration_success_verdict_passes():
    assert _parse_verifier_response("Looks good.\nVERIFICATION: SUCCESS") == []


def test_empty_or_garbage_fails_open():
    assert _parse_verifier_response("") == []
    assert _parse_verifier_response("complete nonsense with no markers") == []


def test_met_word_boundary_does_not_match_inside_unmet():
    # A response whose only enumeration marker is UNMET must fail, not pass
    # via the \bMET\b check accidentally matching inside "UNMET".
    raw = "1. UNMET: nothing was produced.\nVERIFICATION: SUCCESS"
    failures = _parse_verifier_response(raw)
    assert len(failures) == 1
