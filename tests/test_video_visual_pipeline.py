from __future__ import annotations

import json
import unittest
from dataclasses import dataclass

from warrigal.video_visual_pipeline import (
    collect_adjacent_transitions,
    matching_motion_synthesis,
)


@dataclass(frozen=True)
class Frame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int
    frame_index: int


class FakeRepository:
    def __init__(self):
        self.transitions = {
            ("A", "B"): [
                {
                    "transition_id": "TRANS-A-B",
                    "start_timestamp_ms": 0,
                    "end_timestamp_ms": 1000,
                    "status": "derived_unreviewed",
                    "text": "A to B",
                }
            ],
            ("B", "C"): [
                {
                    "transition_id": "TRANS-B-C",
                    "start_timestamp_ms": 1000,
                    "end_timestamp_ms": 2000,
                    "status": "derived_unreviewed",
                    "text": "B to C",
                }
            ],
        }

    def get_visual_transition_for_pair(
        self,
        *,
        video_object_id,
        start_frame_object_id,
        end_frame_object_id,
    ):
        return self.transitions.get(
            (
                start_frame_object_id,
                end_frame_object_id,
            ),
            [],
        )

    def get_video_motion_syntheses(self, video_object_id):
        return [
            {
                "synthesis_id": "MOTION-ONE",
                "status": "derived_unreviewed",
                "transition_ids_json": json.dumps(
                    ["TRANS-A-B", "TRANS-B-C"]
                ),
            }
        ]


class VideoVisualPipelineTests(unittest.TestCase):
    def frames(self):
        return [
            Frame("C", "ACQ-C", 2000, 2),
            Frame("A", "ACQ-A", 0, 0),
            Frame("B", "ACQ-B", 1000, 1),
        ]

    def test_collects_only_ordered_adjacent_transitions(self):
        repository = FakeRepository()

        transitions = collect_adjacent_transitions(
            video_object_id="VIDEO",
            frames=self.frames(),
            repository=repository,
        )

        self.assertEqual(
            [
                row["transition_id"]
                for row in transitions
            ],
            ["TRANS-A-B", "TRANS-B-C"],
        )

    def test_missing_adjacent_transition_stops_pipeline(self):
        repository = FakeRepository()
        del repository.transitions[("B", "C")]

        with self.assertRaisesRegex(
            ValueError,
            "Missing transition",
        ):
            collect_adjacent_transitions(
                video_object_id="VIDEO",
                frames=self.frames(),
                repository=repository,
            )

    def test_reuses_only_identical_active_synthesis(self):
        repository = FakeRepository()

        row = matching_motion_synthesis(
            video_object_id="VIDEO",
            transition_ids=["TRANS-A-B", "TRANS-B-C"],
            repository=repository,
        )

        self.assertEqual(row["synthesis_id"], "MOTION-ONE")

        missing = matching_motion_synthesis(
            video_object_id="VIDEO",
            transition_ids=["DIFFERENT"],
            repository=repository,
        )

        self.assertIsNone(missing)


if __name__ == "__main__":
    unittest.main()
