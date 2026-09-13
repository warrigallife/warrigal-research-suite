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
