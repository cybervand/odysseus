import asyncio
import inspect
import json
import threading
import time
from typing import Dict, Any

from src.constants import MAX_OUTPUT_CHARS


class FindImagesTool:
    """One-call verified image sourcing (doc 013, the images cliff).

    Every prior image path was a multi-step PROCEDURE (search → fetch →
    extract → curl-verify) and five straight runs proved 30B models
    improvise around procedures — inventing URLs, scraping imaginary DOM,
    shipping known-404s. Their native tool-calling is the one thing they
    execute faithfully, so the whole pipeline lives inside this tool:
    Wikimedia Commons API search + server-side HEAD verification. The
    model asks for a subject; it receives URLs that are already proven
    live. Nothing left to improvise.

    2026-08-07 hardening (lodge_website run): a site build calls this once
    per page section, so unthrottled traffic hit Wikimedia's 429 and the
    model retried into the ratelimit; and generic terms ("cottage") came
    back empty because the top Commons hits are SVG maps/heraldry that the
    jpg/png filter drops. Now: filetype:bitmap in the search, more
    candidates, process-wide throttle, result+negative caching, one
    Retry-After-honoring retry, and a STOP-teaching error when 429 persists.
    """

    API = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrnamespace=6&gsrlimit=20&prop=imageinfo"
           "&iiprop=url&iiurlwidth=960&gsrsearch=")
    _UA = "OdysseusFindImages/1.1 (https://github.com/odysseus-dev/odysseus)"

    # Process-wide politeness: one Commons search at a time, spaced out.
    _lock = threading.Lock()
    _last_search = 0.0
    _MIN_SEARCH_INTERVAL_S = 1.5
    _HEAD_SPACING_S = 0.25

    # query -> (expires_ts, results list). Negative results cached briefly
    # so a model retrying the same failing term does not spiral into 429.
    _cache: Dict[str, tuple] = {}
    _CACHE_TTL_S = 900
    _NEG_TTL_S = 90

    def _verify(self, url: str) -> bool:
        import urllib.request
        try:
            time.sleep(self._HEAD_SPACING_S)
            head = urllib.request.Request(
                url, method="HEAD", headers={"User-Agent": self._UA},
            )
            return urllib.request.urlopen(head, timeout=10).status == 200
        except Exception:
            return False

    def _get_json_throttled(self, url: str):
        """Shared politeness gate for EXTERNAL image APIs (Openverse,
        Commons): process-wide serialization, minimum spacing, and one
        Retry-After-honoring retry on 429. SearXNG is LAN-local and skips
        this."""
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": self._UA})
        for attempt in (1, 2):
            with FindImagesTool._lock:
                wait = self._MIN_SEARCH_INTERVAL_S - (time.time() - FindImagesTool._last_search)
                if wait > 0:
                    time.sleep(wait)
                try:
                    return json.load(urllib.request.urlopen(req, timeout=15))
                except urllib.error.HTTPError as e:
                    if e.code == 429 and attempt == 1:
                        try:
                            retry_after = min(float(e.headers.get("Retry-After") or 5), 15)
                        except (TypeError, ValueError):
                            retry_after = 5.0
                        time.sleep(retry_after)
                        continue
                    raise
                finally:
                    FindImagesTool._last_search = time.time()

    def _openverse_images(self, query: str, need: int) -> list:
        """Openverse (api.openverse.org) — the Creative-Commons aggregator:
        600M+ open-licensed images across Flickr, museums, and dozens of
        providers. Keyless, and generic subjects ('cottage') actually hit."""
        import urllib.parse
        data = self._get_json_throttled(
            "https://api.openverse.org/v1/images/"
            f"?q={urllib.parse.quote(query)}&page_size=20"
        )
        found = []
        for r in (data.get("results") or [])[:20]:
            url = str(r.get("url") or "")
            if not url.startswith("http"):
                continue
            if self._verify(url):
                lic = " ".join(x for x in (r.get("license"), r.get("license_version")) if x)
                found.append({"title": str(r.get("title") or "")[:120], "url": url,
                              "license": f"{lic or 'open'} ({r.get('source') or 'openverse'})"})
            if len(found) >= need:
                break
        return found

    def _searx_images(self, query: str, need: int) -> list:
        """Broad web image search through the user's own SearXNG instance —
        LAN-local, multi-engine, no external ratelimit. License unknown, so
        results are labeled; Commons stays the open-license source."""
        import os
        import urllib.parse
        import urllib.request
        base = (os.environ.get("SEARXNG_INSTANCE") or "").rstrip("/")
        if not base:
            return []
        req = urllib.request.Request(
            f"{base}/search?q={urllib.parse.quote(query)}"
            f"&categories=images&format=json&safesearch=1",
            headers={"User-Agent": self._UA},
        )
        data = json.load(urllib.request.urlopen(req, timeout=15))
        found = []
        for r in (data.get("results") or [])[:30]:
            src = str(r.get("img_src") or "")
            if src.startswith("//"):
                src = "https:" + src
            if not src.startswith("http"):
                continue
            if self._verify(src):
                found.append({"title": str(r.get("title") or "")[:120],
                              "url": src, "license": "unverified (web)"})
            if len(found) >= need:
                break
        return found

    def _commons_images(self, query: str, need: int) -> list:
        import urllib.error
        import urllib.parse
        import urllib.request
        # filetype:bitmap keeps Commons from answering generic terms with
        # SVG heraldry/maps that the extension filter would drop to zero.
        req = urllib.request.Request(
            self.API + urllib.parse.quote(f"{query} filetype:bitmap"),
            headers={"User-Agent": self._UA},
        )
        data = self._get_json_throttled(
            self.API + urllib.parse.quote(f"{query} filetype:bitmap"))
        pages = (data.get("query") or {}).get("pages") or {}
        found = []
        for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            title = p.get("title", "")
            if not title.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            ii = (p.get("imageinfo") or [{}])[0]
            url = (ii.get("thumburl") or ii.get("url") or "").split("?")[0]
            if url and self._verify(url):
                found.append({"title": title, "url": url,
                              "license": "open (Wikimedia Commons)"})
            if len(found) >= need:
                break
        return found

    def _search_and_verify(self, query: str, count: int) -> list:
        key = query.lower().strip()
        hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1][:count]

        need = max(count, 3)  # verify a few extra so the cache serves bigger asks
        found: list = []
        errors = []
        # Open-license sources first (Openverse then Commons), the user's
        # own SearXNG web image search as license-unknown filler.
        for source in (self._openverse_images, self._commons_images, self._searx_images):
            if len(found) >= need:
                break
            seen = {f["url"] for f in found}
            try:
                found += [f for f in source(query, need - len(found))
                          if f["url"] not in seen]
            except Exception as e:
                errors.append(e)
        if not found and errors:
            raise errors[0]  # every source failed — surface the first real error
        ttl = self._CACHE_TTL_S if found else self._NEG_TTL_S
        self._cache[key] = (time.time() + ttl, found)
        if len(self._cache) > 200:
            now = time.time()
            for k in [k for k, v in self._cache.items() if v[0] < now]:
                self._cache.pop(k, None)
        return found[:count]

    async def execute(self, content: str, ctx: dict) -> dict:
        raw = (content or "").strip()
        query = raw
        count = 1
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    query = str(parsed.get("query") or parsed.get("subject") or "").strip()
                    c = parsed.get("count")
                    if isinstance(c, int) and 1 <= c <= 5:
                        count = c
            except json.JSONDecodeError:
                pass
        if not query:
            return {"error": 'find_images: provide a subject, e.g. {"query": "mountain lodge winter"}', "exit_code": 1}
        loop = asyncio.get_running_loop()
        try:
            found = await asyncio.wait_for(
                loop.run_in_executor(None, self._search_and_verify, query, count),
                timeout=60,
            )
        except Exception as e:
            if getattr(e, "code", None) == 429:
                return {"error": ("find_images: the image source is rate-limiting us (HTTP 429). "
                                  "STOP calling find_images for now — reuse the URLs you already "
                                  "received, request several images per call (count up to 5) "
                                  "instead of one call per page section, and continue building. "
                                  "Image sourcing will work again in a few minutes."),
                        "exit_code": 1}
            return {"error": f"find_images: {query}: {e}", "exit_code": 1}
        if not found:
            return {"error": f"find_images: no verified images found for '{query}' — try different words (e.g. broader or in English)", "exit_code": 1}
        lines = [f"VERIFIED 200: {f['url']}  ({f['title']}; license {f.get('license', '?')})" for f in found]
        return {"output": f"Verified images for '{query}':\n" + "\n".join(lines)
                          + "\nUse these URLs directly. If one fails to render in the page "
                            "(hotlink protection), drop it and use another or call find_images again.",
                "exit_code": 0}


class WebSearchTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.search import comprehensive_web_search
        progress_cb = ctx.get("progress_cb") if isinstance(ctx, dict) else None
        raw = content.strip()
        query = raw
        time_filter = None
        max_pages = 5
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "query" in parsed:
                    query = str(parsed.get("query", "")).strip()
                    tf = parsed.get("time_filter") or parsed.get("freshness")
                    if isinstance(tf, str) and tf.lower() in ("day", "week", "month", "year"):
                        time_filter = tf.lower()
                    mp = parsed.get("max_pages")
                    if isinstance(mp, int) and 1 <= mp <= 10:
                        max_pages = mp
            except json.JSONDecodeError:
                pass
        if not query:
            query = raw.split("\n")[0].strip()
        if time_filter is None:
            q_lc = query.lower()
            if any(kw in q_lc for kw in ("today", "latest", "breaking", "this morning", "right now", "currently")):
                time_filter = "day"
            elif any(kw in q_lc for kw in ("this week", "past week", "recent news", "last few days")):
                time_filter = "week"
            elif any(kw in q_lc for kw in ("this month", "past month")):
                time_filter = "month"
            elif " news" in q_lc or q_lc.startswith("news ") or q_lc.endswith(" news"):
                time_filter = "week"
        loop = asyncio.get_running_loop()
        if progress_cb:
            await progress_cb({
                "elapsed_s": 0,
                "tail": f"Searching web for: {query[:160]}",
            })
        try:
            text, sources = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: comprehensive_web_search(
                        query,
                        max_pages=max_pages,
                        time_filter=time_filter,
                        return_sources=True,
                    ),
                ),
                timeout=30,
            )
        except asyncio.TimeoutError:
            return {
                "error": f"web_search timed out after 30s: {query[:200]}",
                "exit_code": 1,
            }
        except Exception as e:
            return {
                "error": f"web_search failed: {type(e).__name__}: {str(e) or 'no details'}",
                "exit_code": 1,
            }
        if progress_cb:
            await progress_cb({
                "elapsed_s": 30,
                "tail": "Search completed; preparing sources.",
            })
        output = text[:MAX_OUTPUT_CHARS] if len(text) > MAX_OUTPUT_CHARS else text
        if sources:
            output += "\n\n<!-- SOURCES:" + json.dumps(sources) + " -->"
        return {"output": output, "exit_code": 0}

class WebFetchTool:
    async def execute(self, content: str, ctx: dict) -> dict:
        from src.search.content import fetch_webpage_content
        from src.constants import WEB_FETCH_HARD_MAX_BYTES
        raw = content.strip()
        url = ""
        max_bytes = None
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    url = str(parsed.get("url") or "").strip()
                    # Download-budget override (#3812): "full": true raises the
                    # budget to the hard cap; an explicit max_bytes is clamped
                    # to the hard cap downstream. Default stays the soft cap.
                    if parsed.get("full") is True:
                        max_bytes = WEB_FETCH_HARD_MAX_BYTES
                    mb = parsed.get("max_bytes")
                    if isinstance(mb, int) and mb > 0:
                        max_bytes = mb
            except json.JSONDecodeError:
                url = ""
        if not url:
            url = raw.split("\n")[0].strip()
        if not url or url.startswith("{") or any(c in url for c in (" ", "\t", "\n")):
            return {"error": "web_fetch: provide a single URL or domain, e.g. example.com", "exit_code": 1}
        low = url.lower()
        if "://" in low and not low.startswith(("http://", "https://")):
            return {"error": f"web_fetch: unsupported URL scheme (only http/https): {url[:80]}", "exit_code": 1}
        if not low.startswith(("http://", "https://")):
            url = "https://" + url
        loop = asyncio.get_running_loop()
        try:
            def _fetch():
                kwargs = {"timeout": 10}
                try:
                    sig = inspect.signature(fetch_webpage_content)
                    if "max_bytes" in sig.parameters:
                        kwargs["max_bytes"] = max_bytes
                except (TypeError, ValueError):
                    # Some deployed/test shims may not expose a signature.
                    # Prefer compatibility over failing the whole fetch.
                    pass
                return fetch_webpage_content(url, **kwargs)

            result = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch),
                timeout=30,
            )
        except asyncio.TimeoutError:
            return {"error": f"web_fetch: timed out fetching {url}", "exit_code": 1}
        except Exception as e:
            return {"error": f"web_fetch: {url}: {e}", "exit_code": 1}
        err = result.get("error")
        text = (result.get("content") or "").strip()
        title = result.get("title") or ""

        if not text:
            if err:
                return {"error": f"web_fetch: {url}: {err}", "exit_code": 1}
            return {"error": f"web_fetch: {url}: no readable text content (not HTML, or the page needs JS/login)", "exit_code": 1}

        # Tell the model when the download budget cut the body short and how
        # to get the rest, instead of silently presenting a partial page as
        # the whole thing.
        size_note = ""
        if result.get("truncated"):
            fetched = result.get("fetched_bytes") or 0
            total = result.get("total_bytes")
            total_txt = f" of {total:,} bytes" if total else ""
            size_note = (
                f"[partial content: download stopped at {fetched:,} bytes{total_txt}. "
                f'Re-call with {{"url": "{url}", "full": true}} to fetch up to '
                f"{WEB_FETCH_HARD_MAX_BYTES:,} bytes.]\n\n"
            )

        # The notice must lead the output so the MAX_OUTPUT_CHARS trim below can
        # never drop it. The title is untrusted, uncapped page content, so a
        # giant title ahead of the notice could push it out of range; keep the
        # notice first and cap the title as a second guard.
        if len(title) > 300:
            title = title[:300] + "..."
        header = (f"# {title}\n" if title else "") + f"Source: {url}\n\n"
        # Image URLs the text extraction would otherwise discard — without
        # this section a model asked to find an image can fetch the right
        # page and still have NO way to learn any image's address (it
        # fabricates one instead; qwen, doc 013). Placed before the body so
        # the output cap can't drop it.
        images = result.get("images") or []
        images_note = ""
        if images:
            images_note = "[images on page]\n" + "\n".join(images[:12]) + "\n\n"
        output = size_note + header + images_note + text
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n\n[...truncated]"
        return {"output": output, "exit_code": 0}
