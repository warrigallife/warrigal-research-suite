import json
import unittest

from warrigal.acquisition.manifest import (
    CollectionManifest,
    ManifestLead,
    ManifestResource,
)


class CollectionManifestTests(unittest.TestCase):
    def build_manifest(self):
        return CollectionManifest(
            manifest_id="bunker-semico",
            name=(
                "Bunker of Doom — Semiconductor Projects, "
                "Applications, and Data Books"
            ),
            description=(
                "Bounded semiconductor literature collection discovered "
                "through John Kleinbauer's YouTube channel."
            ),
            discovery_provenance={
                "discovered_via": "John Kleinbauer YouTube",
                "youtube_video": "Bunker of Doom Booklets",
                "youtube_video_id": "9P9KqyALVus",
                "youtube_comment_id":
                    "UgwQ78IYFPj5m-6rAOV4AaABAg",
                "discovery_page":
                    "https://bunkerofdoom.com/lit/semico/index.html",
            },
            resources=[
                ManifestResource(
                    url=(
                        "https://bunkerofdoom.com/lit/semico/"
                        "125-Transistor-Projects-Rufus-Turner.pdf"
                    ),
                    media_type="application/pdf",
                    expected_size_bytes=5280540,
                    status="verified",
                    object_id=(
                        "WRG-OBJ-DC18EA803C13452AB3AA6189ABB3223A"
                    ),
                    acquisition_id=(
                        "WRG-ACQ-0992A1264444466390769F87DEF9406B"
                    ),
                    sha256=(
                        "8abcb16424c3b81c13c4a9e41c254bf"
                        "5a27ca0d9be41b1d786903f1c505ad46b"
                    ),
                ),
                ManifestResource(
                    url=(
                        "https://bunkerofdoom.com/lit/semico/"
                        "individual_transistor_data_sheets.zip"
                    ),
                    media_type="application/zip",
                    status="inventoried",
                ),
            ],
            leads=[
                ManifestLead(
                    locator="https://bunkerofdoom.com/",
                    relationship=(
                        "Potential additional literature collections "
                        "outside the bounded semiconductor inventory."
                    ),
                )
            ],
        )

    def test_manifest_round_trip_is_deterministic(self):
        manifest = self.build_manifest()

        encoded = manifest.to_json()
        restored = CollectionManifest.from_json(encoded)

        self.assertEqual(restored.to_json(), encoded)
        self.assertEqual(
            restored.resources[0].object_id,
            "WRG-OBJ-DC18EA803C13452AB3AA6189ABB3223A",
        )

    def test_manifest_serialization_is_valid_json(self):
        encoded = self.build_manifest().to_json()
        data = json.loads(encoded)

        self.assertEqual(data["manifest_id"], "bunker-semico")
        self.assertEqual(len(data["resources"]), 2)
        self.assertEqual(data["resources"][0]["status"], "verified")
        self.assertEqual(data["leads"][0]["status"], "lead")

    def test_duplicate_resource_urls_are_rejected(self):
        manifest = self.build_manifest()
        manifest.resources.append(manifest.resources[0])

        with self.assertRaisesRegex(
            ValueError,
            "duplicate resource url",
        ):
            manifest.validate()

    def test_unknown_resource_status_is_rejected(self):
        manifest = self.build_manifest()
        manifest.resources[0].status = "probably_downloaded"

        with self.assertRaisesRegex(
            ValueError,
            "unsupported resource status",
        ):
            manifest.validate()

    def test_invalid_sha256_is_rejected(self):
        manifest = self.build_manifest()
        manifest.resources[0].sha256 = "not-a-sha"

        with self.assertRaisesRegex(ValueError, "sha256"):
            manifest.validate()

    def test_resource_requires_absolute_web_url(self):
        manifest = self.build_manifest()
        manifest.resources[0].url = "/lit/semico/book.pdf"

        with self.assertRaisesRegex(
            ValueError,
            "absolute HTTP or HTTPS URL",
        ):
            manifest.validate()

    def test_leads_remain_separate_from_bounded_resources(self):
        manifest = self.build_manifest()

        manifest.validate()

        self.assertEqual(len(manifest.resources), 2)
        self.assertEqual(len(manifest.leads), 1)
        self.assertNotEqual(
            manifest.resources[0].url,
            manifest.leads[0].locator,
        )


if __name__ == "__main__":
    unittest.main()
