"""Name-mention override + find_images always available (doc 008 gate #4).

The external Chroma tool index predated find_images: retrieval for a
message literally saying "use your find_images tool" returned fifteen
image-flavored tools and not find_images. The model, ordered to use a
tool its toolbox lacked, silently substituted web_search and invented
URLs. Two guards now: naming a tool forces its offer, and find_images
is in ALWAYS_AVAILABLE.
"""
import pathlib

import src.agent_loop as al
from src.tool_index import ALWAYS_AVAILABLE


def test_find_images_always_available():
    assert "find_images" in ALWAYS_AVAILABLE


def test_name_mention_override_present():
    src = pathlib.Path(al.__file__).read_text(encoding="utf-8")
    assert "Name-mention override" in src
    assert "_relevant_tools.add(_t)" in src


def test_mention_matching_logic():
    # Mirror of the override's matching rule: tag (>=4 chars) appears as a
    # substring of the lowercased user message.
    from src.agent_tools import TOOL_TAGS
    msg = "use your find_images tool five times then edit the templates"
    hits = {t for t in TOOL_TAGS if len(t) >= 4 and t in msg.lower()}
    assert "find_images" in hits
    # Short/generic tags must not be force-offered by accident ("ls" etc.).
    msg2 = "please also list the files"
    hits2 = {t for t in TOOL_TAGS if len(t) >= 4 and t in msg2.lower()}
    assert "ls" not in hits2
