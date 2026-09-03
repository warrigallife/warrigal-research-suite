from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO

from pypdf import PdfReader

@dataclass
class ExtractedContent:
    """Readable content extracted from an acquired resource."""

    title: str | None
    text: str

class _ReadableHTMLParser(HTMLParser):
    """Collect readable text from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1

        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth > 0:
            self.ignored_depth -= 1

        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.ignored_depth > 0:
            return
        
        text = data.strip()

        if text:
            self.text_parts.append(text)

            if self.in_title:
                self.title_parts.append(text)

def extract_html_content(data: bytes) -> ExtractedContent:
    """Extract readable content from HTML bytes."""

    html = data.decode("utf-8", errors="replace")

    parser = _ReadableHTMLParser()
    parser.feed(html)

    title = " ".join(parser.title_parts).strip() or None
    text = " ".join(parser.text_parts).strip()

    return ExtractedContent(
        title=title,
        text=text,
    )

def extract_pdf_content(data: bytes) -> ExtractedContent:
    """Extract readable content and title metadata from PDF bytes."""

    reader = PdfReader(BytesIO(data))

    metadata = reader.metadata
    title = None

    if metadata is not None:
        title = metadata.title

        if title is not None:
            title = title.strip() or None

    page_text = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            page_text.append(text.strip())

    return ExtractedContent(
        title=title,
        text="\n\n".join(page_text).strip(),
    )

