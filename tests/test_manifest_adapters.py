import unittest

from warrigal.acquisition.manifest import ManifestResource
from warrigal.acquisition.manifest_adapters import (
    make_pdf_manifest_handler,
)
from warrigal.acquisition.web_documents import WebDocumentResult


class ManifestPdfAdapterTests(unittest.TestCase):
    def make_handler(self, ingestor, **kwargs):
        return make_pdf_manifest_handler(
            repository=object(),
            object_store=object(),
            job_id="WRG-JOB-TEST",
            node_id="WRG-NODE-TEST",
            batch_id="WRG-BATCH-TEST",
            collection_id="WRG-COL-TEST",
            discovery_metadata={
                "discovered_via": "test discovery",
            },
            fetcher=object(),
            ingestor=ingestor,
            **kwargs,
        )

    def resource(self):
        return ManifestResource(
            url="https://example.test/manual.pdf",
            media_type="application/pdf",
            expected_size_bytes=1234,
            status="inventoried",
            metadata={
                "resource_note": "bounded test resource",
            },
        )

    def successful_result(self, *, status="ingested"):
        return WebDocumentResult(
            url="https://example.test/manual.pdf",
            final_url="https://cdn.example.test/manual.pdf",
            status=status,
            object_id="WRG-OBJ-TEST",
            acquisition_id="WRG-ACQ-TEST",
            sha256="a" * 64,
            size_bytes=1234,
            passage_count=7,
            deduplicated=(status == "duplicate"),
        )

    def test_pdf_handler_forwards_exact_manifest_resource(self):
        calls = []

        def ingestor(url, **kwargs):
            calls.append((url, kwargs))
            return self.successful_result()

        resource = self.resource()
        handler = self.make_handler(ingestor)

        result = handler(resource)

        self.assertEqual(len(calls), 1)

        url, kwargs = calls[0]

        self.assertEqual(url, resource.url)
        self.assertEqual(
            kwargs["discovery_metadata"]["manifest_resource_url"],
            resource.url,
        )
        self.assertEqual(
            kwargs["discovery_metadata"][
                "manifest_resource_expected_size_bytes"
            ],
            1234,
        )
        self.assertEqual(
            kwargs["discovery_metadata"]["resource_note"],
            "bounded test resource",
        )

        self.assertEqual(result["object_id"], "WRG-OBJ-TEST")
        self.assertEqual(result["acquisition_id"], "WRG-ACQ-TEST")
        self.assertEqual(result["sha256"], "a" * 64)

    def test_pdf_handler_preserves_collection_discovery_metadata(self):
        captured = {}

        def ingestor(url, **kwargs):
            captured.update(kwargs["discovery_metadata"])
            return self.successful_result()

        self.make_handler(ingestor)(self.resource())

        self.assertEqual(
            captured["discovered_via"],
            "test discovery",
        )

    def test_resource_metadata_can_add_specific_provenance(self):
        captured = {}

        resource = self.resource()
        resource.metadata["source_relationship"] = "linked manual"

        def ingestor(url, **kwargs):
            captured.update(kwargs["discovery_metadata"])
            return self.successful_result()

        self.make_handler(ingestor)(resource)

        self.assertEqual(
            captured["source_relationship"],
            "linked manual",
        )

    def test_failed_web_ingestion_becomes_runner_failure(self):
        def ingestor(url, **kwargs):
            return WebDocumentResult(
                url=url,
                final_url=url,
                status="failed",
                error="RuntimeError: simulated failure",
            )

        handler = self.make_handler(ingestor)

        with self.assertRaises(RuntimeError):
            handler(self.resource())

    def test_no_text_is_successfully_preserved(self):
        def ingestor(url, **kwargs):
            return self.successful_result(status="no_text")

        result = self.make_handler(ingestor)(self.resource())

        self.assertEqual(
            result["web_document_status"],
            "no_text",
        )

    def test_duplicate_is_successfully_preserved(self):
        def ingestor(url, **kwargs):
            return self.successful_result(status="duplicate")

        result = self.make_handler(ingestor)(self.resource())

        self.assertEqual(
            result["web_document_status"],
            "duplicate",
        )
        self.assertTrue(result["deduplicated"])

    def test_missing_preservation_identity_is_rejected(self):
        def ingestor(url, **kwargs):
            return WebDocumentResult(
                url=url,
                final_url=url,
                status="ingested",
                object_id=None,
                acquisition_id="WRG-ACQ-TEST",
                sha256="a" * 64,
                size_bytes=1234,
                passage_count=7,
                deduplicated=False,
            )

        handler = self.make_handler(ingestor)

        with self.assertRaises(RuntimeError):
            handler(self.resource())

    def test_non_pdf_resource_is_rejected(self):
        handler = self.make_handler(
            lambda url, **kwargs: self.successful_result()
        )

        resource = ManifestResource(
            url="https://example.test/data.zip",
            media_type="application/zip",
        )

        with self.assertRaises(ValueError):
            handler(resource)


if __name__ == "__main__":
    unittest.main()
