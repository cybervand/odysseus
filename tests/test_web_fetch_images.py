"""web_fetch must surface image URLs (doc 013, the images cliff).

The HTML→text extraction discards img srcs, so a model asked to find an
image could fetch the exact right page and receive prose with no way to
learn any image's address — qwen fabricated Wikimedia URLs because its
world contained no real ones. fetch_webpage_content now returns an
``images`` list and WebFetchTool prints an [images on page] section ahead
of the body so the output cap can't drop it.
"""
from bs4 import BeautifulSoup

from services.search.content import _extract_images


HTML = """
<html><body>
<img src="//upload.wikimedia.org/wikipedia/commons/3/3d/Irish_coffee_01.jpg">
<img src="/w/resources/sprite-icons.png">
<img src="https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Latte_art.jpg/640px-Latte_art.jpg">
<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
<img src="https://commons.wikimedia.org/static/images/footer/wikimedia.png">
<img src="https://example.com/logo.svg">
<img data-src="https://cdn.example.com/lazy-hero.jpg">
</body></html>
"""


def test_extracts_absolute_image_urls():
    soup = BeautifulSoup(HTML, "html.parser")
    imgs = _extract_images(soup, "https://commons.wikimedia.org/wiki/File:Irish_coffee_01.jpg")
    assert "https://upload.wikimedia.org/wikipedia/commons/3/3d/Irish_coffee_01.jpg" in imgs
    assert "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Latte_art.jpg/640px-Latte_art.jpg" in imgs


def test_lazy_loaded_data_src_included():
    soup = BeautifulSoup(HTML, "html.parser")
    imgs = _extract_images(soup, "https://commons.wikimedia.org/x")
    assert "https://cdn.example.com/lazy-hero.jpg" in imgs


def test_chrome_and_data_uris_excluded():
    soup = BeautifulSoup(HTML, "html.parser")
    imgs = _extract_images(soup, "https://commons.wikimedia.org/x")
    joined = "\n".join(imgs)
    assert "data:" not in joined
    assert "sprite" not in joined
    assert "/static/" not in joined
    assert ".svg" not in joined


def test_cap_and_dedupe():
    html = "".join(
        f'<img src="https://e.com/{i % 5}.jpg">' for i in range(40)
    )
    soup = BeautifulSoup(html, "html.parser")
    imgs = _extract_images(soup, "https://e.com/")
    assert len(imgs) == 5  # deduped well under the cap
    soup2 = BeautifulSoup(
        "".join(f'<img src="https://e.com/{i}.jpg">' for i in range(40)),
        "html.parser",
    )
    assert len(_extract_images(soup2, "https://e.com/")) == 12  # capped
