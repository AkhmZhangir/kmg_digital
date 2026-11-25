import unittest

from core.tutor import TutorError
from core.webbuild import select_build_pages


class BuildRangeTest(unittest.TestCase):
    def test_only_units_in_a_valid_range_are_returned(self):
        units = [{"page": n, "text": str(n)} for n in (9, 11, 12)]
        selected, pages = select_build_pages(units, 10, 11)
        self.assertEqual(pages, [11])
        self.assertEqual(selected, [units[1]])

        for a, b in ((0, 10), (9, 13), (11, 9), (10, 10), (True, 12), (9.1, 12)):
            with self.subTest(a=a, b=b), self.assertRaises(TutorError) as failure:
                select_build_pages(units, a, b)
            self.assertEqual(failure.exception.status, 400)

    def test_build_limit_applies_to_selected_pages(self):
        units = [{"page": n, "text": str(n)} for n in range(1, 228)]
        with self.assertRaises(TutorError) as failure:
            select_build_pages(units)
        self.assertEqual(failure.exception.status, 413)
        _, pages = select_build_pages(units, 200, 227)
        self.assertEqual(pages, list(range(200, 228)))
