from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag, urlparse


class _LinkParser(HTMLParser):
    """Collect href values from HTML anchor elements."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return

        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)


def extract_links(html: bytes, base_url: str) -> list[str]:
    """Extract and normalize HTTP/HTTPS links from an HTML document."""

    parser = _LinkParser()
    parser.feed(html.decode("utf-8", errors="replace"))

    links: list[str] = []

    for href in parser.links:
        absolute_url = urljoin(base_url, href)
        absolute_url, _ = urldefrag(absolute_url)

        parsed = urlparse(absolute_url)

        if parsed.scheme not in {"http", "https"}:
            continue

        if absolute_url not in links:
            links.append(absolute_url)

    return links