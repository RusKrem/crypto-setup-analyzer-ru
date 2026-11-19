import unittest

from crypto_setup_analyzer.analysis import _build_first_crossing_lookup


class FirstCrossingLookupTests(unittest.TestCase):
    def test_minimum_lookup_returns_first_value_at_or_below_threshold(self):
        values = [8, 7, 9, 5, 6, 3, 4]
        first = _build_first_crossing_lookup(values, "min")
        self.assertEqual(first(2, 6), 3)
        self.assertEqual(first(4, 3), 5)
        self.assertIsNone(first(6, 2))
        self.assertIsNone(first(len(values), 100))

    def test_maximum_lookup_returns_first_value_at_or_above_threshold(self):
        values = [2, 4, 3, 8, 5, 9, 1]
        first = _build_first_crossing_lookup(values, "max")
        self.assertEqual(first(2, 7), 3)
        self.assertEqual(first(4, 9), 5)
        self.assertIsNone(first(6, 10))

    def test_lookup_matches_naive_search_for_multiple_thresholds(self):
        values = [9, 4, 8, 3, 7, 2, 6, 1, 5]
        for mode in ("min", "max"):
            first = _build_first_crossing_lookup(values, mode)
            for start in range(len(values) + 1):
                for threshold in range(1, 11):
                    if mode == "min":
                        expected = next((i for i in range(start, len(values))
                                         if values[i] <= threshold), None)
                    else:
                        expected = next((i for i in range(start, len(values))
                                         if values[i] >= threshold), None)
                    self.assertEqual(first(start, threshold), expected)

    def test_invalid_lookup_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            _build_first_crossing_lookup([1, 2, 3], "median")


if __name__ == "__main__":
    unittest.main()
