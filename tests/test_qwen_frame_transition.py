from __future__ import annotations

import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from warrigal.qwen_frame_transition import (
    QwenFrameTransitionAnalyser,
    analyse_and_persist_transition,
)


@dataclass(frozen=True)
class Frame:
    frame_object_id: str
    frame_acquisition_id: str
    timestamp_ms: int


class FakeRepository:
    def __init__(self):
        self.saved = []

    def save_visual_transition(self, transition):
        self.saved.append(transition)


class QwenFrameTransitionTests(unittest.TestCase):
    def test_compares_two_images_and_persists_transition(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.gguf"
            projector = root / "projector.gguf"
            before = root / "before.png"
            after = root / "after.png"

            model.write_bytes(b"model")
            projector.write_bytes(b"projector")
            before.write_bytes(b"before")
            after.write_bytes(b"after")

            def runner(command, timeout):
                image_positions = [
                    index
                    for index, value in enumerate(command)
                    if value == "--image"
                ]
                self.assertEqual(len(image_positions), 2)
                self.assertEqual(
                    command[image_positions[0] + 1],
                    str(before.resolve()),
                )
                self.assertEqual(
                    command[image_positions[1] + 1],
                    str(after.resolve()),
                )

                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        "Loading model...\n"
                        "> prompt ... (truncated)\n"
                        "TRANSITION SUMMARY\n"
                        "Two curves appear in the second frame.\n\n"
                        "APPEARED\nTwo fractal curves.\n\n"
                        "DISAPPEARED\nNone.\n"
                        "\n[ Prompt: 1 t/s ]\nExiting...\n"
                    ),
                    stderr="",
                )

            repository = FakeRepository()
            analyser = QwenFrameTransitionAnalyser(
                model_path=model,
                projector_path=projector,
                executable="python",
                runner=runner,
            )

            result = analyse_and_persist_transition(
                video_object_id="VIDEO",
                start_frame=Frame(
                    "FRAME-0",
                    "ACQ-0",
                    0,
                ),
                end_frame=Frame(
                    "FRAME-1",
                    "ACQ-1",
                    1000,
                ),
                start_image_path=before,
                end_image_path=after,
                repository=repository,
                analyser=analyser,
            )

            self.assertTrue(
                result.text.startswith("TRANSITION SUMMARY")
            )
            self.assertNotIn("Loading model", result.text)
            self.assertEqual(result.start_timestamp_ms, 0)
            self.assertEqual(result.end_timestamp_ms, 1000)
            self.assertEqual(repository.saved, [result])

    def test_rejects_reversed_timestamps(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.gguf"
            projector = root / "projector.gguf"
            image = root / "frame.png"

            model.write_bytes(b"model")
            projector.write_bytes(b"projector")
            image.write_bytes(b"image")

            analyser = QwenFrameTransitionAnalyser(
                model_path=model,
                projector_path=projector,
                executable="python",
            )

            with self.assertRaisesRegex(
                ValueError,
                "after start-frame timestamp",
            ):
                analyse_and_persist_transition(
                    video_object_id="VIDEO",
                    start_frame=Frame(
                        "FRAME-2",
                        "ACQ-2",
                        2000,
                    ),
                    end_frame=Frame(
                        "FRAME-1",
                        "ACQ-1",
                        1000,
                    ),
                    start_image_path=image,
                    end_image_path=image,
                    repository=FakeRepository(),
                    analyser=analyser,
                )


if __name__ == "__main__":
    unittest.main()
