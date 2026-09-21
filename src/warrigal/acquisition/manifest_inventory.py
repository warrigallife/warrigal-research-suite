from __future__ import annotations

from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource
from warrigal.acquisition.web import WebFetcher


SizeProbe = Callable[[str], int | None]


def _clean_label(value: str) -> str:
    """Return a stable, human-readable label suitable for a branch segment."""

    value = " ".join(value.split()).strip()
    value = value.replace("/", " & ").replace("\\", " & ")
    value = re.sub(r'[:*?"<>|]+', " ", value)
    return " ".join(value.split()).strip(" .-")


def _page_branch(url: str) -> str:
    path = PurePosixPath(urlparse(url).path)
    stem = path.stem
    if not stem or stem.lower() in {"index", "home"}:
        return "HOME"
    return _clean_label(stem.replace("-", " ").replace("_", " ")).upper()


class _SectionedDocumentParser(HTMLParser):
    """Collect document links with the closest preceding HTML heading."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.current_section = "GENERAL"
        self.documents: list[tuple[str, str, str]] = []
        self._heading_tag: str | None = None
        self._heading_text: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_tag = tag
            self._heading_text = []
        elif tag == "a":
            self._anchor_href = next(
                (value for name, value in attrs if name.lower() == "href" and value),
                None,
            )
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_text.append(data)
        if self._anchor_href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._heading_tag == tag:
            heading = _clean_label("".join(self._heading_text))
            if heading:
                self.current_section = heading.upper()
            self._heading_tag = None
            self._heading_text = []
        elif tag == "a" and self._anchor_href is not None:
            absolute, _ = urldefrag(urljoin(self.base_url, self._anchor_href))
            if urlparse(absolute).scheme in {"http", "https"}:
                title = _clean_label("".join(self._anchor_text))
                self.documents.append((absolute, self.current_section, title))
            self._anchor_href = None
            self._anchor_text = []


def extract_sectioned_document_links(
    html: bytes,
    base_url: str,
) -> list[tuple[str, str, str]]:
    """Return unique supported links as (URL, section, visible label)."""

    parser = _SectionedDocumentParser(base_url)
    parser.feed(html.decode("utf-8", errors="replace"))
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for url, section, title in parser.documents:
        if media_type_for_url(url) is None or url in seen:
            continue
        seen.add(url)
        result.append((url, section, title))
    return result


def media_type_for_url(url: str) -> str | None:
    """Return the supported manifest media type for a resource URL."""

    suffix = PurePosixPath(urlparse(url).path).suffix.lower()

    if suffix == ".pdf":
        return "application/pdf"

    if suffix == ".zip":
        return "application/zip"

    return None


def discover_manifest_resources(
    index_url: str,
    *,
    fetcher: WebFetcher,
    size_probe: SizeProbe,
) -> list[ManifestResource]:
    """
    Discover supported resources from one bounded HTML index.

    Only links present on the supplied index are considered. Linked pages are
    not crawled recursively.
    """

    response = fetcher.fetch(index_url)
    links = extract_sectioned_document_links(
        response.data,
        response.final_url,
    )
    page_branch = _page_branch(response.final_url)

    resources: list[ManifestResource] = []

    for url, section, title in links:
        media_type = media_type_for_url(url)

        if media_type is None:
            continue

        expected_size_bytes = size_probe(url)

        resources.append(
            ManifestResource(
                url=url,
                media_type=media_type,
                expected_size_bytes=expected_size_bytes,
                status="inventoried",
                metadata={
                    "branch": f"{page_branch}/{section}",
                    "source_page": response.final_url,
                    "source_section": section,
                    "link_label": title,
                },
            )
        )

    return resources


def head_content_length(
    url: str,
    *,
    fetcher: WebFetcher,
) -> int | None:
    """
    Probe Content-Length with HEAD without intentionally downloading the body.
    """

    request = Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": "WarrigalResearchSuite/0.1",
        },
    )

    with urlopen(
        request,
        timeout=fetcher.timeout,
        context=fetcher.ssl_context,
    ) as response:
        raw_size = response.headers.get("Content-Length")

    if raw_size is None:
        return None

    size = int(raw_size)

    if size < 0:
        raise ValueError(f"Negative Content-Length returned for {url}")

    return size


def build_collection_manifest(
    *,
    index_url: str,
    manifest_id: str,
    name: str,
    description: str,
    discovery_provenance: dict[str, object],
    fetcher: WebFetcher | None = None,
    size_probe: SizeProbe | None = None,
    metadata: dict[str, object] | None = None,
) -> CollectionManifest:
    """
    Build and validate a bounded collection manifest from one HTML index.

    This inventories supported direct resources only. It does not acquire
    resource bodies and does not crawl linked pages.
    """

    fetcher = fetcher or WebFetcher()

    if size_probe is None:
        size_probe = lambda url: head_content_length(
            url,
            fetcher=fetcher,
        )

    resources = discover_manifest_resources(
        index_url,
        fetcher=fetcher,
        size_probe=size_probe,
    )

    manifest = CollectionManifest(
        manifest_id=manifest_id,
        name=name,
        description=description,
        discovery_provenance=dict(discovery_provenance),
        resources=resources,
        metadata={
            "inventory_source": index_url,
            "inventory_resource_count": len(resources),
            **(metadata or {}),
        },
    )

    manifest.validate()
    return manifest
