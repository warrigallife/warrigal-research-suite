from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warrigal.archive_health import inspect_archive
from warrigal.config import WarrigalConfig
from warrigal.database import initialize_database


class ArchiveHealthTests(unittest.TestCase):
    def config(self, root: Path) -> WarrigalConfig:
        return WarrigalConfig(
            archive_root=root,
            runtime_root=root / "runtime",
            database_path=root / "warrigal.db",
            object_store_path=root / "objects",
            ffmpeg="ffmpeg", ffprobe="ffprobe", whisper="whisper-cli",
            llama="llama-cli", qpdf="qpdf", whisper_model=None,
            qwen_model=None, qwen_projector=None,
        )

    def test_empty_initialized_archive_is_healthy(self):
        with TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            initialize_database(config.database_path).close()
            report = inspect_archive(config)
        self.assertTrue(report.healthy)
        self.assertEqual(report.objects, 0)

    def test_missing_object_and_broken_storage_are_reported(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            connection = initialize_database(config.database_path)
            connection.execute(
                "INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?)",
                ("object-1", "a" * 64, 1, None, None, "now"),
            )
            connection.execute(
                "INSERT INTO storage_locations VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("storage-1", "object-1", "local_archive", str(root / "missing"), None, None, "{}"),
            )
            connection.commit()
            connection.close()
            report = inspect_archive(config)
        self.assertFalse(report.healthy)
        self.assertEqual(report.missing_object_files, ("object-1",))
        self.assertEqual(len(report.broken_storage_paths), 1)


if __name__ == "__main__":
    unittest.main()
