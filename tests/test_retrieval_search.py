import unittest

from warrigal.retrieval.passages import Passage
from warrigal.retrieval.search import search_passages


class SearchPassagesTests(unittest.TestCase):
    def test_full_query_coverage_ranks_first(self):
        passages = [
            Passage(
                index=0,
                text="Ganoderma produces useful compounds.",
            ),
            Passage(
                index=1,
                text="Ganoderma australe produces useful compounds.",
            ),
        ]

        results = search_passages(
            "Ganoderma australe",
            passages,
        )

        self.assertEqual(results[0].passage.index, 1)
        self.assertEqual(results[0].query_coverage, 1.0)

    def test_exact_match_beats_family_match(self):
        passages = [
            Passage(
                index=0,
                text="The organism contains compounds.",
            ),
            Passage(
                index=1,
                text="The organism contain compounds.",
            ),
        ]

        results = search_passages(
            "contain",
            passages,
        )

        self.assertEqual(results[0].passage.index, 1)
        self.assertEqual(
            results[0].exact_matched_terms,
            ("contain",),
        )

    def test_real_term_span_beats_missing_span(self):
        passages = [
            Passage(
                index=0,
                text="Ganoderma australe.",
            ),
            Passage(
                index=1,
                text="Ganoderma.",
                source_title="Australe",
            ),
        ]

        results = search_passages(
            "Ganoderma australe",
            passages,
        )

        self.assertEqual(results[0].passage.index, 0)
        self.assertIsNotNone(results[0].term_span)
        self.assertIsNone(results[1].term_span)

    def test_minimum_query_coverage_filters_results(self):
        passages = [
            Passage(
                index=0,
                text="Ganoderma.",
            ),
            Passage(
                index=1,
                text="Ganoderma australe.",
            ),
        ]

        results = search_passages(
            "Ganoderma australe",
            passages,
            min_query_coverage=1.0,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].passage.index, 1)

    def test_max_results_limits_ranked_results(self):
        passages = [
            Passage(index=0, text="Ganoderma."),
            Passage(index=1, text="Ganoderma australe."),
            Passage(index=2, text="Ganoderma species."),
        ]

        results = search_passages(
            "Ganoderma",
            passages,
            max_results=2,
        )

        self.assertEqual(len(results), 2)

    def test_exact_title_match_beats_family_title_match(self):
        passages = [
            Passage(
                index=1,
                text="background material",
                source_title="Studies",
            ),
            Passage(
                index=0,
                text="background material",
                source_title="Study",
            ),
        ]

        results = search_passages(
            "study",
            passages,
        )

        self.assertEqual(results[0].passage.index, 0)
        self.assertEqual(
            results[0].title_exact_matched_terms,
            ("study",),
        )
        self.assertEqual(
            results[1].title_family_matched_terms,
            ("study",),
        )

    def test_higher_term_frequency_breaks_ranking_tie(self):
        passages = [
            Passage(
                index=0,
                text="Ganoderma background material.",
            ),
            Passage(
                index=1,
                text="Ganoderma Ganoderma background material.",
            ),
        ]

        results = search_passages(
            "Ganoderma",
            passages,
        )

        self.assertEqual(results[0].passage.index, 1)
        self.assertEqual(
            results[0].query_term_frequency,
            (("ganoderma", 2),),
        )
        self.assertEqual(
            results[1].query_term_frequency,
            (("ganoderma", 1),),
        )


if __name__ == "__main__":
    unittest.main()
