import os
import unittest

os.environ.setdefault("GROQ_API_KEY", "gsk_test")

from services import groq_service


class ToQuantityTests(unittest.TestCase):
    def test_valid_quantities(self):
        self.assertEqual(groq_service._to_quantity(2), 2)
        self.assertEqual(groq_service._to_quantity("3"), 3)
        self.assertEqual(groq_service._to_quantity("1,5"), 1.5)
        self.assertEqual(groq_service._to_quantity(2.0), 2)

    def test_missing_or_invalid_defaults_to_one(self):
        for value in (None, "", "abc", 0, -2):
            self.assertEqual(groq_service._to_quantity(value), 1)


if __name__ == "__main__":
    unittest.main()
