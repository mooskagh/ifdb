import unittest

from games.importer.tools import CategorizeUrl


class TestUrlCategorizer(unittest.TestCase):
    def test_gamin_posts_are_forum_links(self):
        result = CategorizeUrl("https://gamin.me/posts/123")

        self.assertEqual(result["urlcat_slug"], "forum")

    def test_discussion_label_is_forum_link(self):
        result = CategorizeUrl("https://example.com/thread", "Обсуждение")

        self.assertEqual(result["urlcat_slug"], "forum")

    def test_hyperbook_comments_are_forum_links(self):
        result = CategorizeUrl(
            "http://hyperbook.ru/comments.php?id=15138858934730"
        )

        self.assertEqual(result["urlcat_slug"], "forum")

    def test_vkvideo_is_video_link(self):
        result = CategorizeUrl("https://vkvideo.ru/video-1_456")

        self.assertEqual(result["urlcat_slug"], "video")
