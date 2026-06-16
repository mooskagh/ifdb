from django.test import SimpleTestCase

from .diff import build_diff


class BuildDiffTest(SimpleTestCase):
    def test_equal_only(self):
        rows = build_diff("one\ntwo", "one\ntwo")

        self.assertEqual([row.tag for row in rows], ["equal", "equal"])
        self.assertEqual(
            [(row.left_no, row.right_no) for row in rows], [(1, 1), (2, 2)]
        )
        self.assertEqual(rows[0].left[0].text, "one")
        self.assertEqual(rows[0].left[0].kind, "equal")

    def test_insert_and_delete_line_numbers(self):
        inserted = build_diff("one", "zero\none")
        deleted = build_diff("one\ntwo", "one")

        self.assertEqual(inserted[0].tag, "insert")
        self.assertIsNone(inserted[0].left_no)
        self.assertEqual(inserted[0].right_no, 1)
        self.assertEqual(inserted[0].right[0].kind, "ins")
        self.assertEqual(deleted[1].tag, "delete")
        self.assertEqual(deleted[1].left_no, 2)
        self.assertIsNone(deleted[1].right_no)
        self.assertEqual(deleted[1].left[0].kind, "del")

    def test_replace_has_char_segments(self):
        rows = build_diff("hello plain world", "hello crisp world")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tag, "replace")
        self.assertEqual((rows[0].left_no, rows[0].right_no), (1, 1))
        self.assertTrue([seg for seg in rows[0].right if seg.kind == "ins"])
        self.assertTrue([seg for seg in rows[0].left if seg.kind == "del"])
