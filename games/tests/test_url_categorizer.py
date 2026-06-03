import unittest

from games.importer.tools import CategorizeUrl


class TestUrlCategorizer(unittest.TestCase):
    def test_gamin_posts_are_forum_links(self):
        result = CategorizeUrl("https://gamin.me/posts/123")

        self.assertEqual(result["urlcat_slug"], "forum")

    def test_discussion_label_is_forum_link(self):
        result = CategorizeUrl("https://example.com/thread", "Обсуждение")

        self.assertEqual(result["urlcat_slug"], "forum")
