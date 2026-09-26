import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warrigal.source_panel import (
    build_instagram_commands,
    build_local_document_commands,
    build_website_commands,
    instagram_paths,
    safe_name,
)
from warrigal.workflows import LOCAL_DOCUMENT_ACTIONS, actions_for


class SourcePanelTests(unittest.TestCase):
    def test_safe_name_accepts_instagram_username_and_url(self):
        self.assertEqual(safe_name("@ScienceWithJahir"), "sciencewithjahir")
        self.assertEqual(
            safe_name("https://www.instagram.com/ScienceWithJahir/"),
            "sciencewithjahir",
        )

    def test_instagram_paths_are_external_and_deterministic(self):
        profile, inventory, checkpoint = instagram_paths("sciencewithjahir")
        self.assertEqual(profile, "sciencewithjahir")
        self.assertEqual(inventory.name, "sciencewithjahir-instagram-inventory.json")
        self.assertEqual(checkpoint.name, "sciencewithjahir-instagram.checkpoint.json")
        self.assertIn("INFORMATION_ARCHIVE", str(inventory))

    def test_complete_instagram_workflow_has_four_steps(self):
        commands = build_instagram_commands("sciencewithjahir", "Complete workflow")
        self.assertEqual(len(commands), 4)
        self.assertIn("warrigal.instagram_profile_inventory", commands[0][1])
        self.assertIn("warrigal.instagram_browser_campaign", commands[1][1])
        self.assertIn("warrigal.instagram_browser_campaign", commands[2][1])
        self.assertIn("warrigal.publish_instagram_collection", commands[3][1])

    def test_website_without_scheme_gets_https(self):
        command = build_website_commands("example.com", "Crawl website")[0][1]
        self.assertEqual(command[-1], "https://example.com")

    def test_local_documents_source_type_is_selectable(self):
        self.assertEqual(
            actions_for("Local Documents"),
            LOCAL_DOCUMENT_ACTIONS,
        )

    def test_build_local_document_commands_ingests_one_pdf(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf_path = Path(temp) / "evidence.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            commands = build_local_document_commands(str(pdf_path), "Ingest one PDF")
            self.assertEqual(len(commands), 1)
            label, command = commands[0]
            self.assertEqual(
                command,
                [sys.executable, "-m", "warrigal.cli", "ingest-pdf", str(pdf_path)],
            )
            self.assertIn("PDF", label)

    def test_build_local_document_commands_ingests_a_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "documents"
            folder.mkdir()
            commands = build_local_document_commands(
                str(folder), "Ingest a folder of PDFs"
            )
            self.assertEqual(len(commands), 1)
            _, command = commands[0]
            self.assertEqual(
                command,
                [sys.executable, "-m", "warrigal.cli", "ingest-archive", str(folder)],
            )

    def test_build_local_document_commands_rejects_folder_for_file_action(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "documents"
            folder.mkdir()
            with self.assertRaisesRegex(ValueError, "not a folder"):
                build_local_document_commands(str(folder), "Ingest one PDF")

    def test_build_local_document_commands_rejects_file_for_folder_action(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf_path = Path(temp) / "evidence.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            with self.assertRaisesRegex(ValueError, "not a single file"):
                build_local_document_commands(
                    str(pdf_path), "Ingest a folder of PDFs"
                )


if __name__ == "__main__":
    unittest.main()
