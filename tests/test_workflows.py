from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from warrigal.config import WarrigalConfig
from warrigal.workflows import (
    INSTAGRAM_ACTIONS,
    WEBSITE_ACTIONS,
    YOUTUBE_ACTIONS,
    actions_for,
    build_workflow_plan,
)


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

    def test_existing_source_actions_are_unchanged_by_local_documents(self):
        self.assertEqual(actions_for("Instagram"), INSTAGRAM_ACTIONS)
        self.assertEqual(actions_for("YouTube"), YOUTUBE_ACTIONS)
        self.assertEqual(actions_for("Website"), WEBSITE_ACTIONS)


class LocalDocumentWorkflowTests(unittest.TestCase):
    def test_actions_are_exactly_ingest_one_pdf_and_ingest_folder(self):
        self.assertEqual(
            actions_for("Local Documents"),
            ("Ingest one PDF", "Ingest a folder of PDFs"),
        )

    def test_ingest_one_pdf_invokes_existing_ingest_pdf_command(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf_path = Path(temp) / "evidence.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")

            plan = build_workflow_plan(
                "Local Documents", str(pdf_path), "Ingest one PDF"
            )

            self.assertEqual(len(plan.steps), 1)
            self.assertEqual(
                plan.steps[0].command,
                (sys.executable, "-m", "warrigal.cli", "ingest-pdf", str(pdf_path)),
            )

    def test_ingest_folder_invokes_existing_ingest_archive_command(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "documents"
            folder.mkdir()

            plan = build_workflow_plan(
                "Local Documents", str(folder), "Ingest a folder of PDFs"
            )

            self.assertEqual(len(plan.steps), 1)
            self.assertEqual(
                plan.steps[0].command,
                (sys.executable, "-m", "warrigal.cli", "ingest-archive", str(folder)),
            )

    def test_folder_target_is_rejected_for_single_pdf_action(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "documents"
            folder.mkdir()
            with self.assertRaisesRegex(ValueError, "not a folder"):
                build_workflow_plan(
                    "Local Documents", str(folder), "Ingest one PDF"
                )

    def test_file_target_is_rejected_for_folder_action(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf_path = Path(temp) / "evidence.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            with self.assertRaisesRegex(ValueError, "not a single file"):
                build_workflow_plan(
                    "Local Documents", str(pdf_path), "Ingest a folder of PDFs"
                )

    def test_non_pdf_file_is_rejected_for_single_pdf_action(self):
        with tempfile.TemporaryDirectory() as temp:
            text_path = Path(temp) / "notes.txt"
            text_path.write_text("not a pdf", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"\.pdf file"):
                build_workflow_plan(
                    "Local Documents", str(text_path), "Ingest one PDF"
                )

    def test_empty_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Choose a local PDF file or folder"):
            build_workflow_plan("Local Documents", "   ", "Ingest one PDF")

    def test_unknown_action_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "Choose a Local Documents action"):
            build_workflow_plan(
                "Local Documents", "/tmp/whatever.pdf", "Delete everything"
            )

    def test_plan_construction_creates_no_files_and_ingests_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf_path = Path(temp) / "evidence.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            before = sorted(str(entry) for entry in Path(temp).iterdir())

            build_workflow_plan("Local Documents", str(pdf_path), "Ingest one PDF")
            try:
                build_workflow_plan(
                    "Local Documents", str(pdf_path), "Ingest a folder of PDFs"
                )
            except ValueError:
                pass

            after = sorted(str(entry) for entry in Path(temp).iterdir())
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
