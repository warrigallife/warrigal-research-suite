from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SPEC = importlib.util.spec_from_file_location(
    "source_panel_under_test",
    Path(__file__).parents[1] / "src" / "warrigal" / "source_panel.py",
)
assert SPEC and SPEC.loader
PANEL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PANEL
SPEC.loader.exec_module(PANEL)


class YouTubePanelTests(unittest.TestCase):
    def test_all_research_layers_is_one_checkpointed_command(self):
        commands = PANEL.build_youtube_commands(
            "https://www.youtube.com/@DutchUncleJohn",
            "All research layers",
        )
        self.assertEqual(len(commands), 1)
        command = commands[0][1]
        self.assertIn("ingest-youtube-channel", command)
        self.assertIn("--checkpoint", command)
        self.assertIn("--posts-checkpoint", command)
        self.assertIn("dutchunclejohn-youtube-channel.checkpoint.json", " ".join(command))


if __name__ == "__main__":
    unittest.main()
