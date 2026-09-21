from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource
from warrigal.website_document_selector import (
    load_existing_selection,
    selected_manifest,
    size_category,
)


def make_manifest() -> CollectionManifest:
    return CollectionManifest(
        manifest_id="website-example",
        name="Example documents",
        description="Example selection.",
        discovery_provenance={"index_url": "https://example.test"},
        resources=[
            ManifestResource("https://example.test/large.pdf", "application/pdf", 900),
            ManifestResource("https://example.test/unknown.pdf", "application/pdf", None),
            ManifestResource("https://example.test/small.pdf", "application/pdf", 100),
        ],
    )


class WebsiteDocumentSelectorTests(unittest.TestCase):
    def test_selection_preserves_manifest_identity_and_sorts_by_size(self):
        manifest = make_manifest()
        result = selected_manifest(
            manifest,
            {
                "https://example.test/large.pdf",
                "https://example.test/small.pdf",
            },
        )
        self.assertEqual(result.manifest_id, manifest.manifest_id)
        self.assertEqual(
            [resource.url for resource in result.resources],
            [
                "https://example.test/small.pdf",
                "https://example.test/large.pdf",
            ],
        )
        self.assertEqual(result.metadata["selection_resource_count"], 2)
        self.assertEqual(len(manifest.resources), 3)

    def test_existing_selection_is_restored(self):
        manifest = make_manifest()
        selection = selected_manifest(
            manifest, {"https://example.test/small.pdf"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected.json"
            path.write_text(selection.to_json(), encoding="utf-8")
            self.assertEqual(
                load_existing_selection(path, manifest.manifest_id),
                {"https://example.test/small.pdf"},
            )

    def test_unknown_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            selected_manifest(make_manifest(), {"https://example.test/missing.pdf"})

    def test_size_categories_are_human_readable(self):
        manifest = make_manifest()
        self.assertEqual(size_category(manifest.resources[0]), "Smaller (≤25 MB)")
        self.assertEqual(size_category(manifest.resources[1]), "Unknown size")
        manifest.resources[0].expected_size_bytes = 26 * 1024 * 1024
        self.assertEqual(size_category(manifest.resources[0]), "Large (>25 MB)")


if __name__ == "__main__":
    unittest.main()
