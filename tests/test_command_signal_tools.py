"""Messages that name commands or paths must get shell/file tools offered.

Live failure: "Continue in hammer-hub/frontend ... run npm install -D
@tailwindcss/vite ... edit vite.config.js ... run npm run build" was
classified as documents/settings/ui — the model received 56 tools
including the full browser suite but NO bash/write_file/edit_file, and
truthfully told the user it couldn't touch the filesystem (who then
called it a liar; it wasn't).
"""
from src.agent_loop import _message_signals_commands


def test_the_live_failure_message_signals_commands():
    msg = ("Continue in hammer-hub/frontend. Tailwind v4 is already installed and has "
           "NO init command — do not run tailwindcss init or any postcss setup. "
           "1) run npm install -D @tailwindcss/vite 2) edit vite.config.js 3) run npm run build")
    assert _message_signals_commands(msg)


def test_path_like_tokens_signal():
    assert _message_signals_commands("hammer-hub/frontend thats the workspace")
    assert _message_signals_commands("look at src/index.css please")


def test_command_words_signal():
    for m in ("pip install requests", "git status?", "run pytest for me",
              "docker restart the thing", "mkdir a folder called x",
              "run it then", "just build it", "execute the script",
              "retry", "deploy it"):
        assert _message_signals_commands(m), m


def test_plain_chat_does_not_signal():
    for m in ("hello there", "write me a haiku about servers",
              "what do you think about the design", "thats a lie just try", ""):
        assert not _message_signals_commands(m), m
