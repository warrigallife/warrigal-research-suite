from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from warrigal.qwen_video_campaign import (
    run_qwen_video_campaign,
)


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    def get_object(self, object_id):
        return self.rows.get(object_id)


class FakeObjectStore:
    def __init__(self, root):
        self.root = root

    def path_for_hash(self, sha256):
        return self.root / sha256


class QwenVideoCampaignTests(unittest.TestCase):
    def test_checkpoints_each_frame_and_skips_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.json"

            for digest in ("hash-one", "hash-two"):
                (root / digest).write_bytes(b"frame")

            frames = (
                SimpleNamespace(
                    frame_object_id="OBJ-ONE",
                    frame_acquisition_id="ACQ-ONE",
                    timestamp_ms=0,
                    frame_index=0,
                ),
                SimpleNamespace(
                    frame_object_id="OBJ-TWO",
                    frame_acquisition_id="ACQ-TWO",
                    timestamp_ms=5000,
                    frame_index=1,
                ),
            )

            repository = FakeRepository({
                "OBJ-ONE": {"sha256": "hash-one"},
                "OBJ-TWO": {"sha256": "hash-two"},
            })
            store = FakeObjectStore(root)
            calls = []

            def fake_analyse(**kwargs):
                calls.append(kwargs["frame_object_id"])
                return SimpleNamespace(
                    observation_id=(
                        "OBS-" + kwargs["frame_object_id"]
                    ),
                    status="derived_unreviewed",
                )

            first = run_qwen_video_campaign(
                frames,
                repository=repository,
                object_store=store,
                analyser=object(),
                checkpoint_path=checkpoint,
                analyse_function=fake_analyse,
            )

            self.assertEqual(first.completed, 2)
            self.assertEqual(first.failed, 0)
            self.assertEqual(calls, ["OBJ-ONE", "OBJ-TWO"])

            second = run_qwen_video_campaign(
                frames,
                repository=repository,
                object_store=store,
                analyser=object(),
                checkpoint_path=checkpoint,
                analyse_function=fake_analyse,
            )

            self.assertEqual(second.selected, 0)
            self.assertEqual(second.completed, 0)
            self.assertEqual(calls, ["OBJ-ONE", "OBJ-TWO"])


if __name__ == "__main__":
    unittest.main()
