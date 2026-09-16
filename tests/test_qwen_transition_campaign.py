from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from warrigal.qwen_transition_campaign import (
    run_qwen_transition_campaign,
)


@dataclass(frozen=True)
class Frame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int
    frame_index: int


class FakeRepository:
    def __init__(self, root):
        self.root = root
        self.transitions = {}
        self.objects = {}

        for name in ("A", "B", "C"):
            path = root / name
            path.write_bytes(name.encode())
            self.objects[name] = {"sha256": name}

    def get_object(self, object_id):
        return self.objects.get(object_id)

    def get_visual_transition_for_pair(
        self,
        *,
        video_object_id,
        start_frame_object_id,
        end_frame_object_id,
    ):
        return self.transitions.get(
            (start_frame_object_id, end_frame_object_id),
            [],
        )


class FakeObjectStore:
    def __init__(self, root):
        self.root = root

    def path_for_hash(self, sha256):
        return self.root / sha256


class TransitionCampaignTests(unittest.TestCase):
    def test_checkpoints_pairs_and_retries_only_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            repository = FakeRepository(root)
            object_store = FakeObjectStore(root)
            attempts = {}

            frames = [
                Frame("C", "ACQ-C", 2000, 2),
                Frame("A", "ACQ-A", 0, 0),
                Frame("B", "ACQ-B", 1000, 1),
            ]

            def analyse(**kwargs):
                start = kwargs["start_frame"].frame_object_id
                end = kwargs["end_frame"].frame_object_id
                key = f"{start}->{end}"
                attempts[key] = attempts.get(key, 0) + 1

                if key == "B->C" and attempts[key] == 1:
                    raise RuntimeError("temporary failure")

                return SimpleNamespace(
                    transition_id=f"TRANS-{key}",
                    status="derived_unreviewed",
                )

            first = run_qwen_transition_campaign(
                video_object_id="VIDEO",
                frames=frames,
                repository=repository,
                object_store=object_store,
                analyser=object(),
                checkpoint_path=checkpoint,
                analyse_function=analyse,
            )

            self.assertEqual(first.selected, 2)
            self.assertEqual(first.completed, 1)
            self.assertEqual(first.failed, 1)
            self.assertEqual(first.skipped, 0)
            self.assertEqual(first.remaining, 0)

            second = run_qwen_transition_campaign(
                video_object_id="VIDEO",
                frames=frames,
                repository=repository,
                object_store=object_store,
                analyser=object(),
                checkpoint_path=checkpoint,
                analyse_function=analyse,
            )

            self.assertEqual(second.selected, 1)
            self.assertEqual(second.completed, 1)
            self.assertEqual(second.failed, 0)
            self.assertEqual(second.skipped, 1)
            self.assertEqual(second.remaining, 0)
            self.assertEqual(attempts["A->B"], 1)
            self.assertEqual(attempts["B->C"], 2)

    def test_rejects_checkpoint_for_different_video(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text(
                '{"video_object_id":"OTHER",'
                '"completed":{},"failed":{}}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "different video",
            ):
                run_qwen_transition_campaign(
                    video_object_id="VIDEO",
                    frames=[
                        Frame("A", "ACQ-A", 0, 0),
                        Frame("B", "ACQ-B", 1000, 1),
                    ],
                    repository=FakeRepository(root),
                    object_store=FakeObjectStore(root),
                    analyser=object(),
                    checkpoint_path=checkpoint,
                )


if __name__ == "__main__":
    unittest.main()
