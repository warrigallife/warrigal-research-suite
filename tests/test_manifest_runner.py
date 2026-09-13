import json
import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.manifest import (
    CollectionManifest,
    ManifestResource,
)
from warrigal.acquisition.manifest_runner import run_collection_manifest


class ManifestRunnerTests(unittest.TestCase):
    def make_manifest(
        self,
        resources,
        *,
        manifest_id="test-manifest",
    ):
        return CollectionManifest(
            manifest_id=manifest_id,
            name="Test collection",
            description="Bounded runner test collection.",
            discovery_provenance={"test": True},
            resources=list(resources),
        )

    def resource(
        self,
        name,
        media_type,
        *,
        status="inventoried",
    ):
        return ManifestResource(
            url=f"https://example.test/{name}",
            media_type=media_type,
            status=status,
        )

    def test_verified_resource_is_skipped_without_handler_call(self):
        calls = []

        def handler(resource):
            calls.append(resource.url)
            raise AssertionError("Verified resource must not be handled.")

        manifest = self.make_manifest(
            [
                self.resource(
                    "verified.pdf",
                    "application/pdf",
                    status="verified",
                )
            ]
        )

        result = run_collection_manifest(
            manifest,
            pdf_handler=handler,
        )

        self.assertEqual(calls, [])
        self.assertEqual(result.count("skipped_verified"), 1)

    def test_routes_pdf_and_zip_to_separate_handlers(self):
        pdf_calls = []
        zip_calls = []

        def pdf_handler(resource):
            pdf_calls.append(resource.url)
            return {"object_id": "WRG-OBJ-PDF"}

        def zip_handler(resource):
            zip_calls.append(resource.url)
            return {"object_id": "WRG-OBJ-ZIP"}

        pdf = self.resource("manual.pdf", "application/pdf")
        archive = self.resource("data.zip", "application/zip")

        result = run_collection_manifest(
            self.make_manifest([pdf, archive]),
            pdf_handler=pdf_handler,
            zip_handler=zip_handler,
        )

        self.assertEqual(pdf_calls, [pdf.url])
        self.assertEqual(zip_calls, [archive.url])
        self.assertEqual(result.count("acquired"), 1)
        self.assertEqual(result.count("archived"), 1)

    def test_runner_only_calls_handlers_for_manifest_resources(self):
        calls = []

        def handler(resource):
            calls.append(resource.url)
            return {}

        allowed = self.resource("allowed.pdf", "application/pdf")

        run_collection_manifest(
            self.make_manifest([allowed]),
            pdf_handler=handler,
        )

        self.assertEqual(calls, [allowed.url])

    def test_unsupported_resource_requires_review(self):
        resource = self.resource(
            "notes.txt",
            "text/plain",
        )

        result = run_collection_manifest(
            self.make_manifest([resource]),
        )

        self.assertEqual(result.count("needs_review"), 1)
        self.assertEqual(result.items[0].action, "unsupported")

    def test_failure_is_checkpointed_and_does_not_stop_later_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"

            failed_pdf = self.resource(
                "broken.pdf",
                "application/pdf",
            )
            good_zip = self.resource(
                "good.zip",
                "application/zip",
            )

            def pdf_handler(resource):
                raise RuntimeError("simulated PDF failure")

            def zip_handler(resource):
                return {"sha256": "zip-sha"}

            result = run_collection_manifest(
                self.make_manifest([failed_pdf, good_zip]),
                pdf_handler=pdf_handler,
                zip_handler=zip_handler,
                checkpoint_path=checkpoint,
            )

            self.assertEqual(result.count("failed"), 1)
            self.assertEqual(result.count("archived"), 1)

            payload = json.loads(
                checkpoint.read_text(encoding="utf-8")
            )

            self.assertEqual(
                payload["resources"][failed_pdf.url]["status"],
                "failed",
            )
            self.assertEqual(
                payload["resources"][good_zip.url]["status"],
                "archived",
            )

    def test_resume_skips_success_and_retries_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"

            first = self.resource(
                "first.pdf",
                "application/pdf",
            )
            second = self.resource(
                "second.pdf",
                "application/pdf",
            )

            first_run_calls = []

            def first_run_handler(resource):
                first_run_calls.append(resource.url)

                if resource.url == second.url:
                    raise RuntimeError("temporary failure")

                return {"object_id": "WRG-OBJ-FIRST"}

            manifest = self.make_manifest([first, second])

            first_result = run_collection_manifest(
                manifest,
                pdf_handler=first_run_handler,
                checkpoint_path=checkpoint,
            )

            self.assertEqual(first_result.count("acquired"), 1)
            self.assertEqual(first_result.count("failed"), 1)

            second_run_calls = []

            def second_run_handler(resource):
                second_run_calls.append(resource.url)
                return {"object_id": "WRG-OBJ-SECOND"}

            second_result = run_collection_manifest(
                manifest,
                pdf_handler=second_run_handler,
                checkpoint_path=checkpoint,
            )

            self.assertEqual(second_run_calls, [second.url])
            self.assertEqual(
                second_result.count("skipped_checkpoint"),
                1,
            )
            self.assertEqual(second_result.count("acquired"), 1)

    def test_checkpoint_for_different_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"

            resource = self.resource(
                "manual.pdf",
                "application/pdf",
            )

            run_collection_manifest(
                self.make_manifest(
                    [resource],
                    manifest_id="manifest-one",
                ),
                pdf_handler=lambda resource: {},
                checkpoint_path=checkpoint,
            )

            with self.assertRaises(ValueError):
                run_collection_manifest(
                    self.make_manifest(
                        [resource],
                        manifest_id="manifest-two",
                    ),
                    pdf_handler=lambda resource: {},
                    checkpoint_path=checkpoint,
                )


if __name__ == "__main__":
    unittest.main()
