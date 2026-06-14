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

    def test_qsp_game_page(self):
        result = CategorizeUrl("https://qsp.org/games/114-noc-v-lesu")

        self.assertEqual(result["urlcat_slug"], "game_page")
        self.assertEqual(result["description"], "Игра на qsp.org")

    def test_qsp_download(self):
        result = CategorizeUrl(
            "https://qsp.org/games/114-noc-v-lesu/download"
        )

        self.assertEqual(result["urlcat_slug"], "download_direct")
        self.assertEqual(result["description"], "Скачать с qsp.org")
