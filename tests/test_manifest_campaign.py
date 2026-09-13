import tempfile
import unittest
from pathlib import Path

from warrigal.acquisition.manifest import CollectionManifest, ManifestResource
from warrigal.acquisition.manifest_campaign import run_manifest_campaign


def make_manifest():
    return CollectionManifest(
        manifest_id="test-campaign",
        name="Test campaign",
        description="Bounded campaign test.",
        discovery_provenance={"source": "unit-test"},
        resources=(
            ManifestResource(
                url="https://example.test/already.pdf",
                media_type="application/pdf",
                status="verified",
                object_id="WRG-OBJ-VERIFIED",
                acquisition_id="WRG-ACQ-VERIFIED",
                sha256="a" * 64,
            ),
            ManifestResource(
                url="https://example.test/one.pdf",
                media_type="application/pdf",
                status="inventoried",
            ),
            ManifestResource(
                url="https://example.test/two.zip",
                media_type="application/zip",
                status="inventoried",
            ),
            ManifestResource(
                url="https://example.test/three.pdf",
                media_type="application/pdf",
                status="inventoried",
            ),
        ),
        metadata={"scope": "test"},
    )


class ManifestCampaignTests(unittest.TestCase):
    def test_limit_selects_only_requested_non_verified_resources(self):
        calls = []

        def pdf_handler(resource):
            calls.append(resource.url)
            return {"stored": True}

        result = run_manifest_campaign(
            make_manifest(),
            pdf_handler=pdf_handler,
            max_resources=1,
        )

        self.assertEqual(
            calls,
            ["https://example.test/one.pdf"],
        )
        self.assertEqual(result.selected_resources, 1)

    def test_verified_resources_do_not_consume_limit(self):
        result = run_manifest_campaign(
            make_manifest(),
            pdf_handler=lambda resource: {"stored": True},
            max_resources=1,
        )

        self.assertEqual(
            result.run_result.items[0].status,
            "skipped_verified",
        )
        self.assertEqual(
            result.run_result.items[1].url,
            "https://example.test/one.pdf",
        )

    def test_limit_does_not_mutate_original_manifest(self):
        manifest = make_manifest()

        run_manifest_campaign(
            manifest,
            pdf_handler=lambda resource: {"stored": True},
            max_resources=1,
        )

        self.assertEqual(len(manifest.resources), 4)
        self.assertEqual(
            [resource.url for resource in manifest.resources],
            [
                "https://example.test/already.pdf",
                "https://example.test/one.pdf",
                "https://example.test/two.zip",
                "https://example.test/three.pdf",
            ],
        )

    def test_unbounded_campaign_preserves_all_resources(self):
        pdf_calls = []
        zip_calls = []

        result = run_manifest_campaign(
            make_manifest(),
            pdf_handler=lambda resource: (
                pdf_calls.append(resource.url) or {"stored": True}
            ),
            zip_handler=lambda resource: (
                zip_calls.append(resource.url) or {"stored": True}
            ),
        )

        self.assertEqual(len(result.run_result.items), 4)
        self.assertEqual(len(pdf_calls), 2)
        self.assertEqual(len(zip_calls), 1)
        self.assertEqual(result.selected_resources, 3)

    def test_invalid_limit_is_rejected_before_handlers_run(self):
        calls = []

        with self.assertRaises(ValueError):
            run_manifest_campaign(
                make_manifest(),
                pdf_handler=lambda resource: calls.append(resource.url),
                max_resources=0,
            )

        self.assertEqual(calls, [])

    def test_checkpoint_is_forwarded_to_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "campaign.json"
            calls = []

            run_manifest_campaign(
                make_manifest(),
                pdf_handler=lambda resource: (
                    calls.append(resource.url) or {"stored": True}
                ),
                checkpoint_path=checkpoint,
                max_resources=1,
            )

            self.assertTrue(checkpoint.exists())
            self.assertEqual(
                calls,
                ["https://example.test/one.pdf"],
            )

            calls.clear()

            run_manifest_campaign(
                make_manifest(),
                pdf_handler=lambda resource: (
                    calls.append(resource.url) or {"stored": True}
                ),
                checkpoint_path=checkpoint,
                max_resources=1,
            )

            self.assertEqual(calls, [])


    def test_resource_size_ceiling_skips_oversized_resource(self):
        manifest = make_manifest()
        manifest.resources[1].expected_size_bytes = 100
        manifest.resources[2].expected_size_bytes = 10_000
        manifest.resources[3].expected_size_bytes = 200

        calls = []

        result = run_manifest_campaign(
            manifest,
            pdf_handler=lambda resource: (
                calls.append(resource.url) or {"stored": True}
            ),
            zip_handler=lambda resource: (
                calls.append(resource.url) or {"stored": True}
            ),
            max_resources=2,
            max_resource_bytes=500,
        )

        self.assertEqual(
            calls,
            [
                "https://example.test/one.pdf",
                "https://example.test/three.pdf",
            ],
        )
        self.assertEqual(result.selected_resources, 2)

    def test_unknown_size_is_not_selected_under_size_ceiling(self):
        manifest = make_manifest()
        manifest.resources[1].expected_size_bytes = None
        manifest.resources[2].expected_size_bytes = 100
        manifest.resources[3].expected_size_bytes = 200

        calls = []

        run_manifest_campaign(
            manifest,
            pdf_handler=lambda resource: (
                calls.append(resource.url) or {"stored": True}
            ),
            zip_handler=lambda resource: (
                calls.append(resource.url) or {"stored": True}
            ),
            max_resources=2,
            max_resource_bytes=500,
        )

        self.assertEqual(
            calls,
            [
                "https://example.test/two.zip",
                "https://example.test/three.pdf",
            ],
        )

    def test_invalid_resource_size_ceiling_is_rejected(self):
        calls = []

        with self.assertRaises(ValueError):
            run_manifest_campaign(
                make_manifest(),
                pdf_handler=lambda resource: calls.append(resource.url),
                max_resources=1,
                max_resource_bytes=-1,
            )

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
