from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from warrigal.config import load_config


class ConfigTests(unittest.TestCase):
    def test_archive_override_drives_default_runtime_path(self):
        with patch.dict(os.environ, {"WARRIGAL_ARCHIVE_ROOT": "/tmp/warrigal-archive"}, clear=True):
            config = load_config()
        self.assertEqual(config.archive_root, Path("/tmp/warrigal-archive"))
        self.assertEqual(
            config.runtime_root,
            Path("/tmp/warrigal-archive/SYSTEM/WARRIGAL/runtime"),
        )

    def test_explicit_paths_and_tools_are_respected(self):
        values = {
            "WARRIGAL_DATABASE_PATH": "/tmp/warrigal.db",
            "WARRIGAL_OBJECT_STORE": "/tmp/objects",
            "WARRIGAL_FFMPEG": "/tools/ffmpeg",
        }
        with patch.dict(os.environ, values, clear=True):
            config = load_config()
        self.assertEqual(config.database_path, Path("/tmp/warrigal.db"))
        self.assertEqual(config.object_store_path, Path("/tmp/objects"))
        self.assertEqual(config.ffmpeg, "/tools/ffmpeg")

    def test_local_toml_supplies_machine_specific_models(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "warrigal.local.toml"
            path.write_text(
                '[paths]\narchive_root = "/archive"\n'
                '[tools]\nllama = "/tools/llama-cli"\n'
                '[models]\nqwen = "/models/qwen.gguf"\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(path)
        self.assertEqual(config.archive_root, Path("/archive"))
        self.assertEqual(config.llama, "/tools/llama-cli")
        self.assertEqual(config.qwen_model, Path("/models/qwen.gguf"))


if __name__ == "__main__":
    unittest.main()
