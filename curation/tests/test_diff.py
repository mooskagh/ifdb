from django.test import SimpleTestCase

from curation.diff import build_diff


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
        self.assertEqual(rows[0].line_text, "hello crisp world")
        self.assertTrue(rows[0].default_checked)

    def test_pair_lines_false_splits_replace(self):
        rows = build_diff(
            "hello plain world", "hello crisp world", pair_lines=False
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].tag, "delete")
        self.assertEqual(rows[0].left_no, 1)
        self.assertIsNone(rows[0].right_no)
        self.assertEqual(rows[0].line_text, "hello plain world")
        self.assertFalse(rows[0].default_checked)

        self.assertEqual(rows[1].tag, "insert")
        self.assertIsNone(rows[1].left_no)
        self.assertEqual(rows[1].right_no, 1)
        self.assertEqual(rows[1].line_text, "hello crisp world")
        self.assertTrue(rows[1].default_checked)

    def test_default_checked_and_line_text_on_mixed_diff(self):
        before = "line1\nline2\nline3"
        after = "line1\nline2_modified\nline4"
        rows = build_diff(before, after, pair_lines=False)

        # line1: equal
        self.assertEqual(rows[0].tag, "equal")
        self.assertEqual(rows[0].line_text, "line1")
        self.assertTrue(rows[0].default_checked)

        # line2, line3 deleted; line2_modified, line4 inserted
        delete_rows = [r for r in rows if r.tag == "delete"]
        insert_rows = [r for r in rows if r.tag == "insert"]
        self.assertTrue(all(not r.default_checked for r in delete_rows))
        self.assertTrue(all(r.default_checked for r in insert_rows))
        self.assertEqual(
            [r.line_text for r in delete_rows], ["line2", "line3"]
        )
        self.assertEqual(
            [r.line_text for r in insert_rows], ["line2_modified", "line4"]
        )
