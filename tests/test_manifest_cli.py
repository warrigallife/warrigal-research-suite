import unittest
from unittest.mock import patch

from warrigal.cli import build_parser, main


class ManifestCLIParserTests(unittest.TestCase):
    def test_parser_accepts_bounded_manifest_campaign(self):
        parser = build_parser()

        args = parser.parse_args(
            [
                "acquire-manifest",
                "manifests/example.json",
                "--checkpoint",
                "workspace/example.checkpoint.json",
                "--max-resources",
                "1",
                "--max-resource-bytes",
                "1000000",
            ]
        )

        self.assertEqual(args.command, "acquire-manifest")
        self.assertEqual(args.manifest, "manifests/example.json")
        self.assertEqual(
            args.checkpoint,
            "workspace/example.checkpoint.json",
        )
        self.assertEqual(args.max_resources, 1)
        self.assertEqual(args.max_resource_bytes, 1_000_000)

    def test_manifest_campaign_requires_checkpoint(self):
        parser = build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "acquire-manifest",
                    "manifests/example.json",
                    "--max-resources",
                    "1",
                ]
            )

    def test_manifest_campaign_requires_resource_limit(self):
        parser = build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "acquire-manifest",
                    "manifests/example.json",
                    "--checkpoint",
                    "workspace/example.checkpoint.json",
                ]
            )


class ManifestCLIOutputTests(unittest.TestCase):
    def test_zero_selection_footer_is_last_output(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import Mock
        import tempfile

        from warrigal.cli import run_acquire_manifest

        manifest = SimpleNamespace(
            manifest_id="example-manifest",
            name="Example manifest",
            description="Example.",
            discovery_provenance={},
        )
        run_result = SimpleNamespace(
            items=[],
            count=lambda status: 0,
        )
        campaign_result = SimpleNamespace(
            selected_resources=0,
            run_result=run_result,
        )

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            checkpoint_path = Path(tmp) / "checkpoint.json"
            manifest_path.write_text("{}", encoding="utf-8")
            output = StringIO()

            with (
                patch(
                    "warrigal.acquisition.manifest.CollectionManifest.from_json",
                    return_value=manifest,
                ),
                patch("warrigal.cli.initialize_database") as database,
                patch("warrigal.cli.WarrigalRepository"),
                patch(
                    "warrigal.cli.Node",
                    return_value=SimpleNamespace(node_id="WRG-NODE-TEST"),
                ),
                patch(
                    "warrigal.cli.Batch",
                    return_value=SimpleNamespace(batch_id="WRG-BATCH-TEST"),
                ),
                patch(
                    "warrigal.cli.Job",
                    return_value=SimpleNamespace(job_id="WRG-JOB-TEST"),
                ),
                patch(
                    "warrigal.cli.Collection",
                    return_value=SimpleNamespace(
                        collection_id="WRG-COL-TEST"
                    ),
                ),
                patch("warrigal.cli.ObjectStore"),
                patch(
                    "warrigal.acquisition.manifest_adapters."
                    "make_pdf_manifest_handler",
                    return_value=Mock(),
                ),
                patch(
                    "warrigal.acquisition.manifest_adapters."
                    "make_web_archive_manifest_handler",
                    return_value=Mock(),
                ),
                patch(
                    "warrigal.acquisition.manifest_campaign."
                    "run_manifest_campaign",
                    return_value=campaign_result,
                ),
                redirect_stdout(output),
            ):
                result = run_acquire_manifest(
                    str(manifest_path),
                    checkpoint_path=str(checkpoint_path),
                    max_resources=1,
                    max_resource_bytes=2_000_000,
                )

        self.assertEqual(result, 0)
        expected_footer = """=== CAMPAIGN COMPLETE ===
SELECTED: 0
ACQUIRED: 0
ARCHIVED: 0
FAILED:   0
NO NEW RESOURCES"""
        self.assertTrue(
            output.getvalue().rstrip().endswith(expected_footer)
        )
        database.return_value.close.assert_called_once()


class ManifestCLIDispatchTests(unittest.TestCase):
    @patch("warrigal.cli.run_acquire_manifest")
    @patch("sys.argv")
    def test_main_dispatches_manifest_campaign(
        self,
        argv,
        run_acquire_manifest,
    ):
        argv.__getitem__.side_effect = None
        argv.__iter__.side_effect = None

        with patch(
            "sys.argv",
            [
                "warrigal",
                "acquire-manifest",
                "manifests/example.json",
                "--checkpoint",
                "workspace/example.checkpoint.json",
                "--max-resources",
                "1",
                "--max-resource-bytes",
                "1000000",
            ],
        ):
            run_acquire_manifest.return_value = 0
            result = main()

        self.assertEqual(result, 0)
        run_acquire_manifest.assert_called_once_with(
            "manifests/example.json",
            checkpoint_path="workspace/example.checkpoint.json",
            max_resources=1,
            max_resource_bytes=1_000_000,
        )


if __name__ == "__main__":
    unittest.main()
