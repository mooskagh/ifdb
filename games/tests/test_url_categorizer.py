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
        result = CategorizeUrl("https://qsp.org/games/114-noc-v-lesu/download")

        self.assertEqual(result["urlcat_slug"], "download_direct")
        self.assertEqual(result["description"], "Скачать с qsp.org")

    def test_axma_game_page(self):
        result = CategorizeUrl("https://axmajs.ru/library/?id=224")

        self.assertEqual(result["urlcat_slug"], "game_page")
        self.assertEqual(result["description"], "Страница на axmajs.ru")

    def test_axma_download(self):
        result = CategorizeUrl(
            "https://axmajs.ru/include/download_zip.php?id=224"
        )

        self.assertEqual(result["urlcat_slug"], "download_direct")
        self.assertEqual(result["description"], "Скачать с axmajs.ru")

    def test_axma_play_online(self):
        result = CategorizeUrl("https://lib.axmajs.ru/BV2APb6M/")

        self.assertEqual(result["urlcat_slug"], "play_online")
        self.assertEqual(result["description"], "Играть онлайн")

    def test_instead_downloader(self):
        result = CategorizeUrl(
            "https://instead-games.ru/downloader.php?file=instead-smetankin-1.1.zip"
        )

        self.assertEqual(result["urlcat_slug"], "download_direct")
        self.assertEqual(result["description"], "Скачать с инстеда")

    def test_instead_download_path(self):
        result = CategorizeUrl(
            "https://instead-games.ru/download/instead-smetankin-1.1.zip"
        )

        self.assertEqual(result["urlcat_slug"], "download_direct")
        self.assertEqual(result["description"], "Скачать с инстеда")

    def test_instead_game_page(self):
        result = CategorizeUrl("https://instead-games.ru/game.php?ID=140")

        self.assertEqual(result["urlcat_slug"], "game_page")
        self.assertEqual(result["description"], "Страница на инстеде")
