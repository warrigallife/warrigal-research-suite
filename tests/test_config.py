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


if __name__ == "__main__":
    unittest.main()

