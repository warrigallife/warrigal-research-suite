from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from warrigal.acquisition.links import extract_links
from warrigal.acquisition.manifest import CollectionManifest, ManifestResource
from warrigal.acquisition.web import WebFetcher


SizeProbe = Callable[[str], int | None]


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
    links = extract_links(response.data, response.final_url)

    resources: list[ManifestResource] = []

    for url in links:
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
