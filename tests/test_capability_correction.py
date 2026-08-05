"""Capability-correction note (doc 008 policy deltas).

Models anchor on their own past capability claims: after one gated turn
they repeat "I don't have shell access" for the rest of the session even
with every tool restored (observed three times, most recently gpt-oss at
disabled_n=0). The helper detects a recent denial while the terminal is
actually enabled; the loop injects one corrective system line.
"""
import src.agent_loop as al


def _msgs(*assistant_texts):
    out = [{"role": "user", "content": "build the site"}]
    for t in assistant_texts:
        out.append({"role": "assistant", "content": t})
        out.append({"role": "user", "content": "go on"})
    return out


# Observed claims, verbatim from the sessions that motivated this.
OBSERVED = [
    "I don’t have permission to invoke bash, npm or any other command-line tool from this environment.",
    "I don’t have direct access to a shell or node runtime from within this environment.",
    "User wants to build site. Can't run shell. Need to explain steps.",
    "Probably cannot execute commands. Better explain that we need correct project path.",
]


def test_observed_denials_trigger_correction():
    for claim in OBSERVED:
        assert al._needs_capability_correction(_msgs(claim), set()), claim


def test_no_denial_no_correction():
    assert not al._needs_capability_correction(
        _msgs("Here is the plan for the site, starting with index.html."), set()
    )


def test_disabled_bash_never_corrects():
    # When bash genuinely IS off, the model's claim is accurate — no note.
    assert not al._needs_capability_correction(_msgs(OBSERVED[0]), {"bash"})


def test_old_denials_age_out():
    # Only the last 3 assistant turns count; a denial 4 turns back with
    # clean turns since means the model already recovered.
    msgs = _msgs(
        OBSERVED[0],
        "Understood, running it now.",
        "Created index.html.",
        "Added styles.css.",
    )
    assert not al._needs_capability_correction(msgs, set())


def test_shell_disabled_phrasing_triggers():
    assert al._needs_capability_correction(
        _msgs("Unfortunately the shell is disabled in this session."), set()
    )
