from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warrigal.qwen_visual import (
    QwenVisualAnalyser,
    analyse_and_persist,
)


class RecordingRepository:
    def __init__(self):
        self.observations = []

    def save_visual_observation(self, observation):
        self.observations.append(observation)


class QwenVisualTests(unittest.TestCase):
    def test_runs_qwen_and_persists_structured_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            projector = root / "mmproj.gguf"
            image = root / "image.png"

            model.write_bytes(b"model")
            projector.write_bytes(b"projector")
            image.write_bytes(b"image")

            commands = []

            def fake_runner(command, timeout_seconds):
                commands.append((command, timeout_seconds))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="Visible hierarchy and labels.",
                    stderr="runtime diagnostic",
                )

            analyser = QwenVisualAnalyser(
                model_path=model,
                projector_path=projector,
                analyser_version="test-version",
                runner=fake_runner,
            )
            repository = RecordingRepository()

            with patch(
                "warrigal.qwen_visual.shutil.which",
                return_value="/test/llama-mtmd-cli",
            ):
                observation = analyse_and_persist(
                    image_path=image,
                    frame_object_id="WRG-OBJ-FRAME",
                    frame_acquisition_id="WRG-ACQ-FRAME",
                    timestamp_ms=12500,
                    repository=repository,
                    analyser=analyser,
                    prompt="Describe visible evidence.",
                )

            self.assertEqual(len(repository.observations), 1)
            self.assertEqual(
                observation.text,
                "Visible hierarchy and labels.",
            )
            self.assertEqual(observation.timestamp_ms, 12500)
            self.assertEqual(
                observation.status,
                "derived_unreviewed",
            )
            self.assertEqual(
                observation.metadata["review_status"],
                "UNREVIEWED",
            )
            self.assertIn("--image-min-tokens", commands[0][0])
            self.assertIn("1024", commands[0][0])


if __name__ == "__main__":
    unittest.main()
