"""Fenced-dialect fallback (doc 012, deepseek-r1/hermes3 families).

These models are served with native tools attached but emit their real calls
as ```bash fences in prose (deepseek-r1 favors heredocs), so the #3222 guard
(skip_fenced for native models) silences their only channel. When a turn has
ZERO native calls and the primary parse finds nothing, _resolve_tool_blocks
re-parses once with fences enabled — for these families only. The strip side
mirrors the decision via the returned used_fenced_fallback flag.
"""
import src.agent_loop as al
from src.tool_parsing import parse_tool_blocks, strip_tool_blocks

# Probe P1 specimen shape: real call fenced as bash, fabricated output in an
# untagged fence (must stay inert), past-tense completion claim.
P1 = (
    "I'll run the command now.\n\n"
    "```bash\necho dialect-probe-1\n```\n\n"
    "Output:\n```\ndialect-probe-1\n```\n\n"
    "The command has been executed successfully."
)

HEREDOC = (
    "Creating the file:\n\n"
    "```bash\ncat << 'EOF' > probe_dir/a.txt\ntwo-step\nEOF\n```\n"
)


def test_fallback_executes_deepseek_fence():
    blocks, used_native, _, _, fenced = al._resolve_tool_blocks(
        P1, [], round_num=1, is_api_model=True, fenced_fallback=True)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
    assert "echo dialect-probe-1" in blocks[0].content
    assert not used_native
    assert fenced is True


def test_guard_intact_for_non_dialect_models():
    blocks, _, _, _, fenced = al._resolve_tool_blocks(
        P1, [], round_num=1, is_api_model=True, fenced_fallback=False)
    assert blocks == []
    assert fenced is False


def test_native_calls_preempt_fallback():
    native = [{"name": "bash", "arguments": '{"command": "ls"}'}]
    blocks, used_native, _, _, fenced = al._resolve_tool_blocks(
        "some prose with ```bash\nrm -rf /\n```", native,
        round_num=1, is_api_model=True, fenced_fallback=True)
    assert used_native
    assert fenced is False
    assert len(blocks) == 1


def test_heredoc_fence_survives_intact():
    blocks, _, _, _, fenced = al._resolve_tool_blocks(
        HEREDOC, [], round_num=1, is_api_model=True, fenced_fallback=True)
    assert fenced is True
    assert len(blocks) == 1
    assert blocks[0].tool_type == "bash"
    assert "<< 'EOF'" in blocks[0].content
    assert "two-step" in blocks[0].content


def test_fabricated_output_fence_stays_inert():
    blocks = parse_tool_blocks(P1, skip_fenced=False)
    assert len(blocks) == 1  # only the tagged bash fence, not the untagged output


def test_textual_models_unaffected():
    blocks, _, _, _, fenced = al._resolve_tool_blocks(
        P1, [], round_num=1, is_api_model=False, fenced_fallback=True)
    assert len(blocks) == 1
    assert fenced is False  # primary parse already had fences enabled


# Rematch-1 specimen (session realdata-deepseek-r1-14b-2077, round 1): ONE
# bash fence interleaving mkdir with write_file heredoc pseudo-commands —
# run as shell, the write_file line is a guaranteed 126/127.
HYBRID = (
    "```bash\n"
    "mkdir -p coffee_deepseek-r1-14b_2077\n"
    "write_file coffee_deepseek-r1-14b_2077/index.html -- <<EOL\n"
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head><title>Copper Warehouse Coffee</title></head>\n"
    "<body><h1>Copper Warehouse Coffee</h1></body>\n"
    "</html>\n"
    "EOL\n"
    "```\n"
)


def test_hybrid_fence_splits_into_bash_and_write():
    blocks = parse_tool_blocks(HYBRID, skip_fenced=False)
    assert [b.tool_type for b in blocks] == ["bash", "write_file"]
    assert "mkdir -p coffee_deepseek-r1-14b_2077" in blocks[0].content
    assert "write_file" not in blocks[0].content
    wf = blocks[1]
    assert wf.content.startswith("coffee_deepseek-r1-14b_2077/index.html\n")
    assert "Copper Warehouse Coffee" in wf.content
    assert "EOL" not in wf.content


def test_dashpath_variant_from_round6():
    text = (
        "```bash\n"
        "write_file --path coffee_x/styles.css <<EOL\n"
        "body { color: peru; }\n"
        "EOL\n"
        "```\n"
    )
    blocks = parse_tool_blocks(text, skip_fenced=False)
    assert len(blocks) == 1
    assert blocks[0].tool_type == "write_file"
    assert blocks[0].content == "coffee_x/styles.css\nbody { color: peru; }"


def test_unterminated_heredoc_still_writes():
    text = "```bash\nwrite_file a/b.txt -- <<EOL\npartial content\n```\n"
    blocks = parse_tool_blocks(text, skip_fenced=False)
    types = [b.tool_type for b in blocks]
    assert "write_file" in types
    wf = next(b for b in blocks if b.tool_type == "write_file")
    assert "partial content" in wf.content


def test_plain_bash_fence_untouched_by_splitter():
    text = "```bash\nmkdir -p x && ls x\n```\n"
    blocks = parse_tool_blocks(text, skip_fenced=False)
    assert [b.tool_type for b in blocks] == ["bash"]
    assert blocks[0].content == "mkdir -p x && ls x"


def test_hybrid_through_resolver_fallback():
    blocks, _, _, _, fenced = al._resolve_tool_blocks(
        HYBRID, [], round_num=1, is_api_model=True, fenced_fallback=True)
    assert fenced is True
    assert [b.tool_type for b in blocks] == ["bash", "write_file"]


def test_strip_mirror_removes_executed_fence():
    stripped = strip_tool_blocks(P1, skip_fenced=False)
    assert "echo dialect-probe-1" not in stripped or "```bash" not in stripped
    kept = strip_tool_blocks(P1, skip_fenced=True)
    assert "```bash" in kept
