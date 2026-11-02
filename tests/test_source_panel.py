import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warrigal import online_search
from warrigal.source_panel import (
    ARCHIVE_SEARCH_PAGE_SIZE,
    ONLINE_SEARCH_ACTIONS,
    build_archive_search_commands,
    build_instagram_commands,
    build_local_document_commands,
    build_website_commands,
    format_archive_search_compact,
    format_archive_search_diagnostics,
    instagram_paths,
    parse_archive_search_results,
    safe_name,
    select_online_search_result,
)
from warrigal.workflows import (
    ARCHIVE_SEARCH_ACTIONS,
    LOCAL_DOCUMENT_ACTIONS,
    WEBSITE_ACTIONS,
    actions_for,
)


def _cli_search_report(result_blocks: list[dict[str, str]], *, query: str = "radionic") -> str:
    """Build a fixture string in the exact shape `run_search` (src/warrigal/cli.py)
    prints for `warrigal.cli search` - one block per result, separated by a
    blank line, using the same field labels. This never runs the real search
    backend or touches the live archive/database; it only reproduces the
    documented, already-existing report format for parser tests."""

    lines = ["", "=== WARRIGAL SEARCH ===", f"QUERY:   {query}", f"RESULTS: {len(result_blocks)}"]
    for block in result_blocks:
        lines.append("")
        lines.append(f"SCORE:          {block.get('score', '0.0')}")
        lines.append(f"COVERAGE:       {block.get('coverage', '0.0')}")
        lines.append(f"MATCHED:        {block.get('matched', '')}")
        lines.append(f"EXACT:          {block.get('exact', '')}")
        lines.append(f"FAMILY:         {block.get('family', '')}")
        lines.append(f"TERM FREQUENCY: {block.get('term_frequency', '()')}")
        lines.append(f"TERM SPAN:      {block.get('term_span', '0')}")
        lines.append(f"TITLE COVERAGE: {block.get('title_coverage', '0.0')}")
        lines.append(f"TITLE MATCHED:  {block.get('title_matched', '')}")
        lines.append(f"TITLE EXACT:    {block.get('title_exact', '')}")
        lines.append(f"TITLE FAMILY:   {block.get('title_family', '')}")
        lines.append(f"TITLE:          {block.get('title', '')}")
        lines.append(f"SOURCE:         {block.get('source', '')}")
        lines.append(f"EVIDENCE GROUP: {block.get('evidence_group', '')}")
        lines.append(f"OBJECT:         {block.get('object_id', '')}")
        lines.append(f"ACQUISITION:    {block.get('acquisition_id', '')}")
        lines.append(f"METHOD:         {block.get('method', '')}")
        lines.append(f"EVIDENCE:       {block.get('text', '')}")
    return "\n".join(lines) + "\n"


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

    def test_archive_search_source_type_is_selectable(self):
        self.assertEqual(actions_for("Archive Search"), ARCHIVE_SEARCH_ACTIONS)

    def test_build_archive_search_commands_invokes_existing_search_command(self):
        commands = build_archive_search_commands("warrigal provenance", "Search archive")
        self.assertEqual(len(commands), 1)
        label, command = commands[0]
        self.assertEqual(
            command,
            [sys.executable, "-m", "warrigal.cli", "search", "warrigal provenance"],
        )
        self.assertIn("archive", label.lower())

    def test_build_archive_search_commands_rejects_empty_query(self):
        with self.assertRaisesRegex(ValueError, "Enter a search query"):
            build_archive_search_commands("   ", "Search archive")


class ArchiveSearchResultsDisplayTests(unittest.TestCase):
    """Focused tests for the Archive Search compact results display, using
    small hand-built fixtures that mimic the existing CLI report format -
    no live search, archive, or database access."""

    def test_parse_extracts_title_preview_source_and_diagnostics(self):
        report = _cli_search_report(
            [
                {
                    "title": "Radionic Devices Overview",
                    "source": "https://example.test/radionics.html",
                    "text": "Radionic devices have been described in historical texts.",
                    "score": "0.83",
                    "coverage": "0.50",
                    "object_id": "obj-123",
                    "acquisition_id": "acq-456",
                }
            ]
        )
        results = parse_archive_search_results(report)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["title"], "Radionic Devices Overview")
        self.assertEqual(result["source"], "https://example.test/radionics.html")
        self.assertEqual(
            result["text"],
            "Radionic devices have been described in historical texts.",
        )
        self.assertEqual(result["score"], "0.83")
        self.assertEqual(result["coverage"], "0.50")
        self.assertEqual(result["object_id"], "obj-123")

    def test_parse_handles_zero_results(self):
        report = _cli_search_report([], query="ganoderma")
        self.assertEqual(parse_archive_search_results(report), [])

    def test_compact_view_shows_title_preview_and_source(self):
        results = parse_archive_search_results(
            _cli_search_report(
                [
                    {
                        "title": "Example Title",
                        "source": "https://example.test/page",
                        "text": "Short passage text.",
                    }
                ]
            )
        )
        compact = format_archive_search_compact(results, 0, 20)
        self.assertIn("Example Title", compact)
        self.assertIn("Short passage text.", compact)
        self.assertIn("https://example.test/page", compact)

    def test_compact_view_truncates_long_passage_text(self):
        long_text = "word " * 200  # far longer than the preview bound
        results = parse_archive_search_results(
            _cli_search_report(
                [{"title": "Long Passage", "source": "https://example.test", "text": long_text}]
            )
        )
        compact = format_archive_search_compact(results, 0, 20)
        self.assertIn("...", compact)
        self.assertNotIn(long_text.strip(), compact)

    def test_compact_view_uses_placeholders_for_missing_title_and_source(self):
        results = [{"text": "Evidence with no title or source recorded."}]
        compact = format_archive_search_compact(results, 0, 20)
        self.assertIn("(untitled)", compact)
        self.assertIn("(no source recorded)", compact)

    def test_compact_view_excludes_diagnostic_fields(self):
        results = parse_archive_search_results(
            _cli_search_report(
                [
                    {
                        "title": "Result One",
                        "source": "https://example.test/one",
                        "text": "Evidence text one.",
                        "score": "0.91",
                        "coverage": "0.75",
                        "matched": "radionic, device",
                    }
                ]
            )
        )
        compact = format_archive_search_compact(results, 0, 20)
        self.assertNotIn("0.91", compact)
        self.assertNotIn("0.75", compact)
        self.assertNotIn("score=", compact)
        self.assertNotIn("radionic, device", compact)

    def test_diagnostics_view_contains_score_and_coverage(self):
        results = parse_archive_search_results(
            _cli_search_report(
                [
                    {
                        "title": "Result One",
                        "source": "https://example.test/one",
                        "text": "Evidence text one.",
                        "score": "0.91",
                        "coverage": "0.75",
                    }
                ]
            )
        )
        diagnostics = format_archive_search_diagnostics(results, 0, 20)
        self.assertIn("score=0.91", diagnostics)
        self.assertIn("coverage=0.75", diagnostics)
        # The diagnostics view is a separate rendering from the compact one;
        # it should not be laid out as the numbered "N. <title>" list.
        self.assertNotIn("1. Result One", diagnostics)

    def test_initial_page_is_bounded_to_page_size(self):
        blocks = [
            {
                "title": f"Result {i}",
                "source": f"https://example.test/{i}",
                "text": f"Evidence text {i}.",
            }
            for i in range(1, ARCHIVE_SEARCH_PAGE_SIZE + 10)
        ]
        results = parse_archive_search_results(_cli_search_report(blocks))
        self.assertEqual(len(results), ARCHIVE_SEARCH_PAGE_SIZE + 9)

        first_page = format_archive_search_compact(results, 0, ARCHIVE_SEARCH_PAGE_SIZE)
        for i in range(1, ARCHIVE_SEARCH_PAGE_SIZE + 1):
            self.assertIn(f"Result {i}", first_page)
        for i in range(ARCHIVE_SEARCH_PAGE_SIZE + 1, ARCHIVE_SEARCH_PAGE_SIZE + 9):
            self.assertNotIn(f"Result {i}", first_page)

    def test_show_more_reveals_results_beyond_the_initial_page(self):
        blocks = [
            {
                "title": f"Result {i}",
                "source": f"https://example.test/{i}",
                "text": f"Evidence text {i}.",
            }
            for i in range(1, ARCHIVE_SEARCH_PAGE_SIZE + 10)
        ]
        results = parse_archive_search_results(_cli_search_report(blocks))

        second_page = format_archive_search_compact(
            results, ARCHIVE_SEARCH_PAGE_SIZE, ARCHIVE_SEARCH_PAGE_SIZE
        )
        self.assertIn(f"Result {ARCHIVE_SEARCH_PAGE_SIZE + 1}", second_page)
        self.assertNotIn("Result 1\n", second_page)

    def test_archive_search_command_composition_unaffected_by_display_changes(self):
        # Guards against the display work above accidentally changing what
        # command gets run for Archive Search.
        commands = build_archive_search_commands("warrigal provenance", "Search archive")
        self.assertEqual(len(commands), 1)
        label, command = commands[0]
        self.assertEqual(
            command,
            [sys.executable, "-m", "warrigal.cli", "search", "warrigal provenance"],
        )
        self.assertIn("archive", label.lower())


class OnlineSearchWiringTests(unittest.TestCase):
    """Confirms Online Search's panel-level wiring (its fixed action list,
    and that it is deliberately excluded from
    `warrigal.workflows.actions_for`/`build_workflow_plan`) without
    touching or depending on Archive Search's own constants or behavior -
    see `ArchiveSearchResultsDisplayTests` above, left unmodified."""

    def test_online_search_has_a_single_fixed_action(self):
        self.assertEqual(ONLINE_SEARCH_ACTIONS, ("Search",))

    def test_online_search_is_not_registered_in_workflows_actions_for(self):
        with self.assertRaisesRegex(ValueError, "Unsupported source type"):
            actions_for("Online Search")

    def test_archive_search_actions_are_unaffected_by_online_search_addition(self):
        self.assertEqual(actions_for("Archive Search"), ARCHIVE_SEARCH_ACTIONS)


class OnlineSearchAcquireBridgeTests(unittest.TestCase):
    """Confirms the Online-Search-to-acquisition bridge: selecting one
    Online Search result resolves to the right result object, and the
    existing Website "Acquire this URL only" action it is re-pointed at
    is untouched. Does not instantiate `SourcePanel` itself (a live Tk
    root) - only the pure, Tk-independent pieces the GUI handler calls,
    matching this file's existing convention for `safe_name`,
    `parse_archive_search_results`, etc."""

    def _results(self) -> list[online_search.OnlineSearchResult]:
        return [
            online_search.OnlineSearchResult(
                title="Ganoderma australe - IUCN Red List",
                url="https://redlist.info/iucn/species_view/100745",
                snippet="Conservation assessment.",
            ),
            online_search.OnlineSearchResult(
                title="Ganoderma australe - Wikipedia",
                url="https://en.wikipedia.org/wiki/Ganoderma_australe",
                snippet="A species of fungus.",
            ),
        ]

    def test_selects_the_requested_one_based_result(self):
        selected = select_online_search_result(self._results(), 2)
        self.assertEqual(
            selected.url, "https://en.wikipedia.org/wiki/Ganoderma_australe"
        )

    def test_rejects_index_below_one(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 2"):
            select_online_search_result(self._results(), 0)

    def test_rejects_index_past_the_last_result(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 2"):
            select_online_search_result(self._results(), 3)

    def test_rejects_any_index_when_there_are_no_results(self):
        with self.assertRaisesRegex(ValueError, "run a search first"):
            select_online_search_result([], 1)

    def test_acquire_this_url_only_action_still_exists_for_the_bridge_to_use(self):
        # The bridge re-points the panel at this existing Website action
        # by name (see `SourcePanel._acquire_selected_online_result`) -
        # if it were ever renamed, that handler would silently break.
        self.assertIn("Acquire this URL only", WEBSITE_ACTIONS)

    def test_bridged_acquire_command_is_identical_to_a_manually_typed_website_url(self):
        selected = self._results()[1]
        bridged_command = build_website_commands(
            selected.url, "Acquire this URL only"
        )
        manual_command = build_website_commands(
            "https://en.wikipedia.org/wiki/Ganoderma_australe",
            "Acquire this URL only",
        )
        self.assertEqual(bridged_command, manual_command)


if __name__ == "__main__":
    unittest.main()
