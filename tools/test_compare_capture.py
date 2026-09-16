import unittest
from compare_capture import compare


class CompareTest(unittest.TestCase):
    def test_repeated_text_is_matched_by_occurrence(self):
        result = compare([{"text": "네"}], [{"text": "네"}, {"text": "네"}])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["sample_recall"], 0.5)

    def test_timestamps_outside_tolerance_do_not_match(self):
        result = compare([{"text": "a", "source_time": 10000}], [{"text": "a", "source_time": 20000}])
        self.assertEqual(result["matched"], 0)

    def test_nearest_timestamp_is_used(self):
        result = compare([{"text": "a", "source_time": 1000}, {"text": "a", "source_time": 6000}],
                         [{"text": "a", "source_time": 5500}, {"text": "a", "source_time": 1000}])
        self.assertEqual(result["matched"], 2)

    def test_empty_sample_does_not_claim_perfect_coverage(self):
        self.assertIsNone(compare([], [])["sample_recall"])

    def test_nearest_match_can_be_reassigned_to_avoid_false_missing(self):
        captured = [{"text": "a", "source_time": 0}, {"text": "a", "source_time": 4000}]
        truth = [{"text": "a", "source_time": 3000}, {"text": "a", "source_time": 8000}]
        self.assertEqual(compare(captured, truth)["matched"], 2)


if __name__ == "__main__":
    unittest.main()
