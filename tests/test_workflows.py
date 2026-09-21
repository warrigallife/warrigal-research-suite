from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from warrigal.config import WarrigalConfig
from warrigal.workflows import actions_for, build_workflow_plan


def test_config(root: Path) -> WarrigalConfig:
    return WarrigalConfig(
        archive_root=root / "archive-root",
        runtime_root=root / "runtime",
        database_path=root / "warrigal.db",
        object_store_path=root / "objects",
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        whisper="whisper-cli",
        llama="llama-cli",
        qpdf="qpdf",
        whisper_model=None,
        qwen_model=None,
        qwen_projector=None,
    )


class WorkflowPlanTests(unittest.TestCase):
    def test_actions_are_shared_and_source_specific(self):
        self.assertIn("Complete workflow", actions_for("Instagram"))
        self.assertIn("All research layers", actions_for("YouTube"))
        self.assertIn("Discover links", actions_for("Website"))

    def test_plan_construction_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = build_workflow_plan(
                "Instagram",
                "sciencewithjahir",
                "Complete workflow",
                config=test_config(root),
            )
            self.assertEqual(len(plan.steps), 4)
            self.assertFalse((root / "runtime").exists())
            self.assertFalse((root / "archive-root").exists())

    def test_panel_command_adapter_returns_mutable_legacy_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = build_workflow_plan(
                "YouTube",
                "https://www.youtube.com/@DutchUncleJohn",
                "Discover channel inventory",
                config=test_config(Path(temp)),
            )
            commands = plan.panel_commands()
            self.assertIsInstance(commands, list)
            self.assertIsInstance(commands[0][1], list)
            self.assertEqual(commands[0][1][-1], "inventory")

    def test_selected_website_verification_has_one_checkpoint_argument(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = build_workflow_plan(
                "Website",
                "https://www.radionictech.com/",
                "Verify selected documents",
                config=test_config(Path(temp)),
            )
            self.assertEqual(plan.steps[0].command.count("--checkpoint"), 1)

    def test_unknown_action_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "Choose a website action"):
            build_workflow_plan(
                "Website", "example.com", "Download everything blindly"
            )


if __name__ == "__main__":
    unittest.main()
