import unittest

from warrigal.retrieval.query import analyze_query, canonical_word


class QueryAnalysisTests(unittest.TestCase):
    def test_low_information_terms_are_filtered(self):
        analysis = analyze_query(
            "What does Ganoderma australe contain?"
        )

        self.assertEqual(
            analysis.all_terms,
            (
                "what",
                "does",
                "ganoderma",
                "australe",
                "contain",
            ),
        )
        self.assertEqual(
            analysis.retrieval_terms,
            (
                "ganoderma",
                "australe",
                "contain",
            ),
        )
        self.assertEqual(
            analysis.filtered_terms,
            (
                "what",
                "does",
            ),
        )

    def test_unknown_scientific_terms_are_preserved(self):
        terms = (
            "species",
            "analysis",
            "triterpenes",
            "polysaccharides",
            "ganoderma",
            "australe",
        )

        for term in terms:
            with self.subTest(term=term):
                self.assertEqual(
                    canonical_word(term),
                    term,
                )


if __name__ == "__main__":
    unittest.main()
