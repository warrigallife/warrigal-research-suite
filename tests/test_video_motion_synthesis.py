from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.video_motion_synthesis import (
    QwenMotionSynthesiser,
    ordered_transition_timeline,
    synthesise_motion_and_persist,
)


class FakeRepository:
    def __init__(self):
        self.saved = []

    def save_video_motion_synthesis(self, synthesis):
        self.saved.append(synthesis)


class VideoMotionSynthesisTests(unittest.TestCase):
    def test_orders_contiguous_transitions_and_persists(self):
        transitions = [
            {
                "transition_id": "TRANS-2",
                "start_timestamp_ms": 1000,
                "end_timestamp_ms": 2000,
                "status": "derived_unreviewed",
                "text": "Both curves became more complex.",
            },
            {
                "transition_id": "TRANS-1",
                "start_timestamp_ms": 0,
                "end_timestamp_ms": 1000,
                "status": "derived_unreviewed",
                "text": "Two curves appeared.",
            },
        ]

        with TemporaryDirectory() as temporary:
            model = Path(temporary) / "model.gguf"
            model.write_bytes(b"model")

            def runner(command, timeout):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "Loading model...\n"
                        "> prompt ... (truncated)\n"
                        "VIDEO MOTION OVERVIEW\n"
                        "Two curves appear and grow more complex.\n\n"
                        "CHRONOLOGICAL PROGRESSION\n"
                        "0-1s: appearance. 1-2s: complexity.\n\n"
                        "PERSISTENT ELEMENTS\nLabels.\n\n"
                        "MAJOR VISUAL CHANGES\nCurve geometry.\n\n"
                        "UNCERTAINTIES AND LIMITS\n"
                        "Only sampled frames were compared.\n\n"
                        "EVIDENCE COVERAGE\n0-2 seconds.\n"
                        "\n[ Prompt: 1 t/s ]\nExiting...\n"
                    ),
                    stderr="",
                )

            repository = FakeRepository()
            analyser = QwenMotionSynthesiser(
                model_path=model,
                executable="python",
                runner=runner,
            )

            result = synthesise_motion_and_persist(
                video_object_id="VIDEO",
                video_acquisition_id="ACQ",
                transitions=transitions,
                repository=repository,
                analyser=analyser,
            )

            self.assertEqual(
                result.transition_ids,
                ["TRANS-1", "TRANS-2"],
            )
            self.assertEqual(result.start_timestamp_ms, 0)
            self.assertEqual(result.end_timestamp_ms, 2000)
            self.assertTrue(
                result.text.startswith("VIDEO MOTION OVERVIEW")
            )
            self.assertNotIn("Loading model", result.text)
            self.assertEqual(repository.saved, [result])

    def test_rejects_gap_in_transition_sequence(self):
        transitions = [
            {
                "transition_id": "TRANS-1",
                "start_timestamp_ms": 0,
                "end_timestamp_ms": 1000,
                "status": "derived_unreviewed",
                "text": "First",
            },
            {
                "transition_id": "TRANS-2",
                "start_timestamp_ms": 2000,
                "end_timestamp_ms": 3000,
                "status": "derived_unreviewed",
                "text": "Second",
            },
        ]

        with self.assertRaisesRegex(
            ValueError,
            "not contiguous",
        ):
            ordered_transition_timeline(transitions)


if __name__ == "__main__":
    unittest.main()
