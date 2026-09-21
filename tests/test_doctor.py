from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from warrigal.config import WarrigalConfig
from warrigal.doctor import collect_checks


class DoctorTests(unittest.TestCase):
    def test_reports_resolved_core_and_optional_configuration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            runtime = archive / "runtime"
            objects = root / "objects"
            database = root / "warrigal.db"
            archive.mkdir()
            runtime.mkdir()
            objects.mkdir()
            database.touch()
            config = WarrigalConfig(
                archive_root=archive,
                runtime_root=runtime,
                database_path=database,
                object_store_path=objects,
                ffmpeg="ffmpeg",
                ffprobe="ffprobe",
                whisper="whisper-cli",
                llama="llama-cli",
                qpdf="qpdf",
                whisper_model=None,
                qwen_model=None,
                qwen_projector=None,
            )
            checks = collect_checks(
                config,
                module_finder=lambda _name: object(),
                executable_finder=lambda name: f"/tools/{name}",
            )
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["Database"].status, "OK")
        self.assertEqual(by_name["ffmpeg"].status, "OK")
        self.assertEqual(by_name["Whisper model"].status, "NOT CONFIGURED")
        self.assertFalse(by_name["Whisper model"].required)


if __name__ == "__main__":
    unittest.main()
