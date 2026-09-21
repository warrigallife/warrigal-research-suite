from __future__ import annotations

import unittest

from warrigal.acquisition.manifest_inventory import (
    build_collection_manifest,
    discover_manifest_resources,
    extract_sectioned_document_links,
    media_type_for_url,
)
from warrigal.acquisition.web import WebResponse


class FakeFetcher:
    def __init__(self, html: bytes) -> None:
        self.html = html
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebResponse:
        self.calls.append(url)

        return WebResponse(
            requested_url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            data=self.html,
        )


class ManifestInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index_url = "https://example.test/library/index.html"

        self.html = b"""
        <html>
          <body>
            <a href="manual-one.pdf">Manual one</a>
            <a href="/library/data.zip">Data</a>
            <a href="notes.txt">Notes</a>
            <a href="manual-one.pdf#page=2">Duplicate PDF</a>
            <a href="subdirectory/">Subdirectory</a>
          </body>
        </html>
        """

        self.sizes = {
            "https://example.test/library/manual-one.pdf": 1234,
            "https://example.test/library/data.zip": 5678,
        }

    def test_media_type_for_supported_resources(self) -> None:
        self.assertEqual(
            media_type_for_url("https://example.test/book.PDF"),
            "application/pdf",
        )
        self.assertEqual(
            media_type_for_url("https://example.test/archive.ZIP"),
            "application/zip",
        )
        self.assertIsNone(
            media_type_for_url("https://example.test/readme.txt")
        )

    def test_discovers_only_supported_direct_resources(self) -> None:
        fetcher = FakeFetcher(self.html)

        resources = discover_manifest_resources(
            self.index_url,
            fetcher=fetcher,
            size_probe=self.sizes.get,
        )

        self.assertEqual(fetcher.calls, [self.index_url])
        self.assertEqual(len(resources), 2)

        self.assertEqual(
            resources[0].url,
            "https://example.test/library/manual-one.pdf",
        )
        self.assertEqual(resources[0].media_type, "application/pdf")
        self.assertEqual(resources[0].expected_size_bytes, 1234)
        self.assertEqual(resources[0].status, "inventoried")

        self.assertEqual(
            resources[1].url,
            "https://example.test/library/data.zip",
        )
        self.assertEqual(resources[1].media_type, "application/zip")
        self.assertEqual(resources[1].expected_size_bytes, 5678)
        self.assertEqual(
            resources[0].metadata["branch"],
            "HOME/GENERAL",
        )

    def test_preserves_page_sections_as_publication_branches(self) -> None:
        html = b"""
        <h2>Rare information</h2>
        <a href="radionics.pdf"><span>Radionics manual</span></a>
        <h2>Recipes / Cooking</h2>
        <a href="bread.pdf">Bread recipes</a>
        """
        resources = discover_manifest_resources(
            "https://example.test/free-ebooks.html",
            fetcher=FakeFetcher(html),
            size_probe=lambda _url: 100,
        )

        self.assertEqual(
            [resource.metadata["branch"] for resource in resources],
            [
                "FREE EBOOKS/RARE INFORMATION",
                "FREE EBOOKS/RECIPES & COOKING",
            ],
        )
        self.assertEqual(
            resources[1].metadata["link_label"],
            "Bread recipes",
        )

    def test_sectioned_link_extraction_deduplicates_fragment_links(self) -> None:
        links = extract_sectioned_document_links(
            b"""
            <h3>History</h3>
            <a href="book.pdf#page=2">Book</a>
            <a href="book.pdf">Duplicate</a>
            """,
            self.index_url,
        )
        self.assertEqual(
            links,
            [("https://example.test/library/book.pdf", "HISTORY", "Book")],
        )

    def test_does_not_recursively_crawl_linked_pages(self) -> None:
        fetcher = FakeFetcher(self.html)

        discover_manifest_resources(
            self.index_url,
            fetcher=fetcher,
            size_probe=self.sizes.get,
        )

        self.assertEqual(fetcher.calls, [self.index_url])

    def test_manifest_preserves_collection_provenance(self) -> None:
        fetcher = FakeFetcher(self.html)

        manifest = build_collection_manifest(
            index_url=self.index_url,
            manifest_id="example-library",
            name="Example Library",
            description="A bounded test collection.",
            discovery_provenance={
                "discovered_via": "test source",
                "discovery_page": self.index_url,
            },
            fetcher=fetcher,
            size_probe=self.sizes.get,
        )

        self.assertEqual(manifest.manifest_id, "example-library")
        self.assertEqual(len(manifest.resources), 2)
        self.assertEqual(
            manifest.discovery_provenance["discovered_via"],
            "test source",
        )
        self.assertEqual(
            manifest.metadata["inventory_source"],
            self.index_url,
        )
        self.assertEqual(
            manifest.metadata["inventory_resource_count"],
            2,
        )

    def test_manifest_serialization_is_deterministic(self) -> None:
        first = build_collection_manifest(
            index_url=self.index_url,
            manifest_id="example-library",
            name="Example Library",
            description="A bounded test collection.",
            discovery_provenance={"discovered_via": "test"},
            fetcher=FakeFetcher(self.html),
            size_probe=self.sizes.get,
        )

        second = build_collection_manifest(
            index_url=self.index_url,
            manifest_id="example-library",
            name="Example Library",
            description="A bounded test collection.",
            discovery_provenance={"discovered_via": "test"},
            fetcher=FakeFetcher(self.html),
            size_probe=self.sizes.get,
        )

        self.assertEqual(first.to_json(), second.to_json())

    def test_missing_content_length_remains_unknown(self) -> None:
        fetcher = FakeFetcher(
            b'<a href="unknown.pdf">Unknown size</a>'
        )

        resources = discover_manifest_resources(
            self.index_url,
            fetcher=fetcher,
            size_probe=lambda _url: None,
        )

        self.assertEqual(len(resources), 1)
        self.assertIsNone(resources[0].expected_size_bytes)


if __name__ == "__main__":
    unittest.main()
