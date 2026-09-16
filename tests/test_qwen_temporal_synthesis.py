from __future__ import annotations

import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.video_temporal_synthesis import (
    QwenTemporalAnalyser,
    semantic_synthesise_and_persist,
)


@dataclass(frozen=True)
class Frame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int
    frame_index: int


class FakeRepository:
    def __init__(self):
        self.saved = []
        self.observations = {
            "FRAME-0": [
                {
                    "observation_id": "OBS-0",
                    "status": "derived_unreviewed",
                    "text": (
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
                        "VISIBLE OBJECTS:\nTwo fractal curves\n\n"
                        "READABLE TEXT:\nDragon Curve\nLévy C Curve\n"
                    ),
                }
            ],
        }

    def get_visual_observations_for_frame(self, object_id):
        return self.observations.get(object_id, [])

    def save_video_temporal_synthesis(self, synthesis):
        self.saved.append(synthesis)


class QwenTemporalSynthesisTests(unittest.TestCase):
    def test_semantic_result_preserves_evidence_and_is_saved(self):
        with TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.gguf"
            model.write_bytes(b"model")

            def runner(command, timeout):
                prompt = command[command.index("--prompt") + 1]
                response = (
                    "Loading model...\n"
                    "model: fake.gguf\n"
                    "> Analyse this ordered set ... (truncated)\n"
                    "INITIAL STATE\nLabels are visible at 0 seconds.\n\n"
                    + "OBSERVED TEMPORAL CHANGES\n"
                    + "Two curves appear by 5 seconds.\n\n"
                    + "PERSISTENT ELEMENTS\n"
                    + "Both labels remain visible.\n\n"
                    + "UNCERTAIN OR UNRESOLVED CHANGES\n"
                    + "Continuous movement is not established.\n\n"
                    + "OVERALL SAMPLED PROGRESSION\n"
                    + "The sampled video progresses from labels to curves.\n"
                    + "\n[ Prompt: 1 t/s | Generation: 1 t/s ]\n"
                    + "Exiting...\n"
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=response,
                    stderr="",
                )

            repository = FakeRepository()
            analyser = QwenTemporalAnalyser(
                model_path=model,
                executable="python",
                runner=runner,
            )

            result = semantic_synthesise_and_persist(
                video_object_id="VIDEO",
                video_acquisition_id="VIDEO-ACQ",
                frames=[
                    Frame("FRAME-5", "ACQ-5", 5000, 1),
                    Frame("FRAME-0", "ACQ-0", 0, 0),
                ],
                repository=repository,
                analyser=analyser,
            )

            self.assertIn(
                "Two curves appear by 5 seconds",
                result.text,
            )
            self.assertTrue(
                result.text.startswith("INITIAL STATE")
            )
            self.assertNotIn("Loading model", result.text)
            self.assertEqual(
                result.timeline[0]["sections"]["READABLE TEXT"],
                ["Dragon Curve", "Lévy C Curve"],
            )
            self.assertEqual(
                result.observation_ids,
                ["OBS-0", "OBS-5"],
            )
            self.assertEqual(result.frame_count, 2)
            self.assertTrue(
                result.metadata["semantic_temporal_synthesis"]
            )
            self.assertEqual(repository.saved, [result])


if __name__ == "__main__":
    unittest.main()
