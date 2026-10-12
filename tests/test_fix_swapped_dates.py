import os
import unittest
from datetime import date

os.environ.setdefault("GROQ_API_KEY", "gsk_test")

import fix_swapped_dates as fix


def serial(y, m, d):
    return (date(y, m, d) - fix.EPOCH).days


class CorrectedSerialTests(unittest.TestCase):
    def test_swaps_day_and_month_using_displayed_text(self):
        # "03/10/2026" (3 October) was stored as 10 March
        self.assertEqual(fix.corrected_serial(serial(2026, 3, 10), "03/10/2026"), serial(2026, 10, 3))

    def test_keeps_time_of_day(self):
        raw = serial(2026, 12, 10) + 0.5
        new = fix.corrected_serial(raw, "12/10/2026 12:00:00")
        self.assertAlmostEqual(new, serial(2026, 10, 12) + 0.5)

    def test_unpadded_displayed_date(self):
        self.assertEqual(fix.corrected_serial(serial(2026, 9, 10), "9/10/2026"), serial(2026, 10, 9))

    def test_text_and_empty_cells_are_ignored(self):
        self.assertIsNone(fix.corrected_serial("14/09/2026", "14/09/2026"))
        self.assertIsNone(fix.corrected_serial("", ""))

    def test_same_day_and_month_needs_no_change(self):
        self.assertIsNone(fix.corrected_serial(serial(2026, 10, 10), "10/10/2026"))

    def test_date_already_displayed_as_dd_mm_is_not_touched(self):
        # stored 3 October, shown "03/10/2026" as dd/mm: already correct
        self.assertIsNone(fix.corrected_serial(serial(2026, 10, 3), "03/10/2026"))


if __name__ == "__main__":
    unittest.main()
