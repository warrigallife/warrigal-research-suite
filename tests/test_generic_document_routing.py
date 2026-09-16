from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warrigal.acquisition.manifest import (
    CollectionManifest,
    ManifestResource,
)
from warrigal.acquisition.manifest_campaign import (
    run_manifest_campaign,
)
from warrigal.acquisition.manifest_runner import (
    run_collection_manifest,
)


class GenericDocumentRoutingTests(unittest.TestCase):
    def manifest(self):
        return CollectionManifest(
            manifest_id="generic-document-routing-test",
            name="Generic document routing test",
            description="Test generic document routing.",
            discovery_provenance={},
            resources=(
                ManifestResource(
                    url="https://example.test/document.doc",
                    media_type="application/msword",
                    status="inventoried",
                    expected_size_bytes=100,
                    metadata={"branch": "test"},
                ),
            ),
            leads=(),
            metadata={},
        )

    def test_runner_routes_word_document(self):
        calls = []

        def document_handler(resource):
            calls.append(resource.url)
            return {"object_id": "test-object"}

        result = run_collection_manifest(
            self.manifest(),
            document_handler=document_handler,
        )

        self.assertEqual(
            calls,
            ["https://example.test/document.doc"],
        )
        self.assertEqual(result.items[0].status, "acquired")
        self.assertEqual(
            result.items[0].action,
            "document_acquisition",
        )

    def test_campaign_forwards_document_handler(self):
        with TemporaryDirectory() as temporary:
            calls = []

            def document_handler(resource):
                calls.append(resource.url)
                return {"object_id": "test-object"}

            result = run_manifest_campaign(
                self.manifest(),
                document_handler=document_handler,
                checkpoint_path=(
                    Path(temporary) / "checkpoint.json"
                ),
                max_resources=1,
            )

            self.assertEqual(
                calls,
                ["https://example.test/document.doc"],
            )
            self.assertEqual(
                result.run_result.items[0].status,
                "acquired",
            )


if __name__ == "__main__":
    unittest.main()
