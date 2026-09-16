from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.database import initialize_database
from warrigal.models import VideoTemporalSynthesis
from warrigal.repository import WarrigalRepository
from warrigal.video_temporal_synthesis import (
    synthesise_and_persist,
    synthesise_temporal_change,
)


@dataclass(frozen=True)
class Frame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int
    frame_index: int


class FakeRepository:
    def __init__(self, observations):
        self.observations = observations
        self.saved = []

    def get_visual_observations_for_frame(self, object_id):
        return self.observations.get(object_id, [])

    def save_video_temporal_synthesis(self, synthesis):
        self.saved.append(synthesis)


class VideoTemporalSynthesisTests(unittest.TestCase):
    def test_orders_frames_and_records_observed_change(self):
        frames = [
            Frame("FRAME-5", "ACQ-5", 5000, 1),
            Frame("FRAME-0", "ACQ-0", 0, 0),
        ]
        observations = {
            "FRAME-0": [
                {
                    "observation_id": "OBS-0",
                    "status": "derived_unreviewed",
                    "text": (
                        "VISIBLE SUBJECTS:\nUNKNOWN\n\n"
                        "VISIBLE OBJECTS:\nText elements\n\n"
                        "READABLE TEXT:\nDragon Curve\nLévy C Curve\n"
                    ),
                }
            ],
            "FRAME-5": [
                {
                    "observation_id": "OBS-5",
                    "status": "derived_unreviewed",
                    "text": (
                        "VISIBLE SUBJECTS:\nUNKNOWN\n\n"
                        "VISIBLE OBJECTS:\n"
                        "Two fractal curves\n\n"
                        "READABLE TEXT:\n"
                        "Dragon Curve\nLévy C Curve\n"
                    ),
                }
            ],
        }
        repository = FakeRepository(observations)

        result = synthesise_and_persist(
            video_object_id="VIDEO",
            video_acquisition_id="VIDEO-ACQ",
            frames=frames,
            repository=repository,
        )

        self.assertEqual(result.frame_count, 2)
        self.assertEqual(
            result.observation_ids,
            ["OBS-0", "OBS-5"],
        )
        self.assertEqual(
            result.timeline[0]["timestamp_ms"],
            0,
        )
        self.assertIn(
            "Two fractal curves",
            result.timeline[1]["added_terms"],
        )
        self.assertIn("0.000s", result.text)
        self.assertIn("5.000s", result.text)
        self.assertFalse(
            result.metadata["continuous_motion_inferred"]
        )
        self.assertEqual(repository.saved, [result])

    def test_missing_observation_stops_synthesis(self):
        frame = Frame("MISSING", "ACQ", 0, 0)

        with self.assertRaisesRegex(
            ValueError,
            "frames lack observations: MISSING",
        ):
            synthesise_temporal_change(
                video_object_id="VIDEO",
                video_acquisition_id="VIDEO-ACQ",
                frames=[frame],
                repository=FakeRepository({}),
            )

    def test_repository_persists_and_reads_synthesis(self):
        with TemporaryDirectory() as temporary:
            database = initialize_database(
                Path(temporary) / "warrigal.db"
            )
            repository = WarrigalRepository(database)

            database.execute("PRAGMA foreign_keys = OFF")
            synthesis = VideoTemporalSynthesis(
                video_object_id="VIDEO",
                video_acquisition_id="ACQUISITION",
                text="Temporal evidence",
                frame_count=2,
                observation_ids=["OBS-1", "OBS-2"],
                timeline=[
                    {"timestamp_ms": 0},
                    {"timestamp_ms": 5000},
                ],
            )

            repository.save_video_temporal_synthesis(synthesis)
            stored = repository.get_video_temporal_syntheses(
                "VIDEO"
            )

            self.assertEqual(len(stored), 1)
            self.assertEqual(
                stored[0]["synthesis_id"],
                synthesis.synthesis_id,
            )
            self.assertEqual(
                json.loads(stored[0]["observation_ids_json"]),
                ["OBS-1", "OBS-2"],
            )
            self.assertEqual(
                json.loads(stored[0]["timeline_json"])[1][
                    "timestamp_ms"
                ],
                5000,
            )
            database.close()


if __name__ == "__main__":
    unittest.main()
