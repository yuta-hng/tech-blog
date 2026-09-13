import json
import unittest
from pathlib import Path

import evaluate


ROOT = Path(__file__).resolve().parents[1]


class EvaluateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))

    def test_normalization_matches_previous_experiment(self):
        reference = self.data["reference"]
        case = next(case for case in self.data["cases"] if case["name"] == "clean_with_hints")
        score = evaluate.evaluate_case(reference, case["hypothesis"])
        self.assertEqual(score["normalized_cer"]["reference_characters"], 338)
        self.assertEqual(score["normalized_cer"]["substitutions"], 60)
        self.assertEqual(score["normalized_cer"]["deletions"], 26)
        self.assertEqual(score["normalized_cer"]["insertions"], 0)
        self.assertAlmostEqual(score["normalized_cer"]["cer"], 86 / 338)

    def test_whitespace_wer_exposes_japanese_tokenization_problem(self):
        reference = self.data["reference"]
        case = next(case for case in self.data["cases"] if case["name"] == "clean_with_hints")
        score = evaluate.evaluate_case(reference, case["hypothesis"])
        self.assertEqual(score["whitespace_wer"]["reference_tokens"], 6)
        self.assertEqual(score["whitespace_wer"]["insertions"], 26)
        self.assertAlmostEqual(score["whitespace_wer"]["wer"], 32 / 6)

        self.assertEqual(score["linebreak_as_space_wer"]["reference_tokens"], 14)
        self.assertEqual(score["linebreak_as_space_wer"]["insertions"], 18)
        self.assertAlmostEqual(score["linebreak_as_space_wer"]["wer"], 32 / 14)

    def test_sudachi_b_score_is_reproducible(self):
        reference = self.data["reference"]
        case = next(case for case in self.data["cases"] if case["name"] == "clean_with_hints")
        score = evaluate.evaluate_case(reference, case["hypothesis"])
        self.assertEqual(score["sudachi_b_wer"]["reference_tokens"], 157)
        self.assertEqual(score["sudachi_b_wer"]["substitutions"], 19)
        self.assertEqual(score["sudachi_b_wer"]["deletions"], 2)
        self.assertEqual(score["sudachi_b_wer"]["insertions"], 1)
        self.assertAlmostEqual(score["sudachi_b_wer"]["wer"], 22 / 157)


if __name__ == "__main__":
    unittest.main()
