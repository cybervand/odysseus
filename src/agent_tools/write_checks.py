"""Write-time syntax + image-reference checks (doc 017 follow-on, 2026-08-08).

Both daily-driver models build working sites whose IMAGES break: mismatched
tags (a stray </div> observed live), img srcs pointing at files that were
never downloaded, and — the sneakiest — hotlink error pages saved as .jpg
by curl, so the file exists while its bytes are HTML. All three are
deterministic to detect the moment the file is written, which is the only
teaching moment small models reliably use.

Advisory only: the write always succeeds; the note rides in the tool result
(and therefore the verifier's actions snapshot, so an ignored failure
becomes an UNMET item). Checks are picked by extension and must stay CHEAP:
ast.parse / node --check / json.loads / a Jinja-blind tag balancer, plus
magic-byte + existence checks for <img> srcs and a small capped HEAD probe
for remote ones.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from typing import List, Optional

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}

_TAG_RE = re.compile(
    r"<\s*(/)?\s*([a-zA-Z][a-zA-Z0-9-]*)((?:\"[^\"]*\"|'[^']*'|[^<>\"'])*)(/)?\s*>")
_IMG_SRC_RE = re.compile(r"<img[^>]*?src\s*=\s*[\"']([^\"']+)[\"']", re.I)

_MAX_PROBLEMS = 6
_MAX_REMOTE_CHECKS = 3
_REMOTE_TIMEOUT_S = 4


def _blank_spans(text: str, pattern: str, flags=re.S) -> str:
    """Replace matches with same-shape whitespace so line numbers survive."""
    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return re.sub(pattern, _blank, text, flags=flags)


def _strip_non_html(text: str) -> str:
    """Blind the tag balancer to Jinja constructs, comments, scripts, styles."""
    text = _blank_spans(text, r"<!--.*?-->")
    text = _blank_spans(text, r"\{#.*?#\}")
    text = _blank_spans(text, r"\{%.*?%\}")
    text = _blank_spans(text, r"\{\{.*?\}\}")
    text = _blank_spans(text, r"<script\b.*?</script\s*>", re.S | re.I)
    text = _blank_spans(text, r"<style\b.*?</style\s*>", re.S | re.I)
    return text


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _check_html_tags(content: str) -> List[str]:
    src = _strip_non_html(content)
    stack: list = []
    problems: List[str] = []
    for m in _TAG_RE.finditer(src):
        closing, name, self_close = m.group(1), m.group(2).lower(), m.group(4)
        line = _line_of(src, m.start())
        if name in _VOID_TAGS or self_close:
            if closing and name in _VOID_TAGS:
                problems.append(
                    f"line {line}: </{name}> — {name} is a void element and "
                    f"never takes a closing tag")
            continue
        if not closing:
            stack.append((name, line))
            continue
        if stack and stack[-1][0] == name:
            stack.pop()
            continue
        open_names = [n for n, _ in stack]
        if name in open_names:
            while stack and stack[-1][0] != name:
                n, ln = stack.pop()
                problems.append(
                    f"line {line}: </{name}> arrived while <{n}> (line {ln}) "
                    f"is still open — missing </{n}>")
            if stack:
                stack.pop()
        else:
            problems.append(f"line {line}: </{name}> has no matching open tag")
        if len(problems) >= _MAX_PROBLEMS:
            return problems
    for n, ln in stack[:3]:
        problems.append(f"<{n}> opened at line {ln} is never closed")
    return problems


def _magic_is_image(path: str) -> Optional[bool]:
    """True/False = readable verdict; None = unreadable."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return None
    if head.startswith(b"\xff\xd8\xff"):
        return True                                   # jpeg
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True                                   # png
    if head.startswith((b"GIF87a", b"GIF89a")):
        return True                                   # gif
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return True                                   # webp
    if head.startswith(b"BM"):
        return True                                   # bmp
    if head.startswith(b"\x00\x00\x01\x00"):
        return True                                   # ico
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<svg", b"<?xml")):
        return True                                   # svg
    return False


def _resolve_local_src(html_path: str, src: str) -> Optional[str]:
    """Best-effort resolution of an <img src> to a file on disk. Covers the
    flask shape (templates/x.html referencing /static/...) and plain
    relative paths."""
    rel = src.split("?")[0].split("#")[0].lstrip("/")
    d = os.path.dirname(os.path.abspath(html_path))
    candidates = []
    if not src.startswith("/"):
        candidates.append(os.path.join(d, rel))
    candidates.append(os.path.join(d, rel))
    candidates.append(os.path.abspath(os.path.join(d, "..", rel)))
    seen = set()
    for c in candidates:
        c = os.path.normpath(c)
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return None


def _head_ok(url: str) -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": "OdysseusWriteCheck/1.0"})
        return urllib.request.urlopen(req, timeout=_REMOTE_TIMEOUT_S).status == 200
    except Exception:
        return False


def _check_images(path: str, content: str) -> List[str]:
    problems: List[str] = []
    seen = set()
    remote_checked = 0
    for src in _IMG_SRC_RE.findall(content):
        if src in seen or src.startswith("data:") or "{{" in src or "{%" in src:
            continue
        seen.add(src)
        if src.startswith(("http://", "https://", "//")):
            if remote_checked >= _MAX_REMOTE_CHECKS:
                continue
            remote_checked += 1
            url = "https:" + src if src.startswith("//") else src
            if not _head_ok(url):
                problems.append(
                    f'remote image not reachable: {url} — replace it '
                    f'(find_images returns verified URLs)')
            continue
        f = _resolve_local_src(path, src)
        if f is None:
            problems.append(
                f'src="{src}": file NOT FOUND — download it first or fix the path')
        elif _magic_is_image(f) is False:
            problems.append(
                f'src="{src}": file exists but is NOT an image (likely an HTML '
                f'error page saved by a blocked download) — re-download from a '
                f'working URL')
        if len(problems) >= _MAX_PROBLEMS:
            break
    return problems


def check_written_file(path: str) -> Optional[str]:
    """Post-write health check. Reads the file from disk (ground truth).
    Returns an advisory note string, or None when everything passes."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    problems: List[str] = []
    if ext == ".py":
        try:
            ast.parse(content)
        except SyntaxError as e:
            problems.append(f"python syntax error: line {e.lineno}: {e.msg}")
    elif ext in (".js", ".mjs", ".cjs"):
        node = shutil.which("node")
        if node:
            try:
                r = subprocess.run([node, "--check", path],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode != 0:
                    tail = (r.stderr or r.stdout).strip().splitlines()
                    problems.append("javascript syntax error: "
                                    + (tail[-1][:200] if tail else "node --check failed"))
            except (subprocess.TimeoutExpired, OSError):
                pass
    elif ext == ".json":
        try:
            json.loads(content)
        except ValueError as e:
            problems.append(f"invalid json: {e}")
    elif ext in (".html", ".htm", ".jinja", ".j2"):
        problems += _check_html_tags(content)
        problems += _check_images(path, content)
    elif ext == ".css":
        opens, closes = content.count("{"), content.count("}")
        if opens != closes:
            problems.append(f"css braces unbalanced: {opens} '{{' vs {closes} '}}'")
    if not problems:
        return None
    return ("CHECK FAILED — fix these before calling the task done:\n"
            + "\n".join(f"- {p}" for p in problems[:_MAX_PROBLEMS]))
