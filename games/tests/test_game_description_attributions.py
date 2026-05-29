from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase


class GameDescriptionAttributionTest(SimpleTestCase):
    def test_single_attribution_uses_singular_site_word(self):
        html = render_to_string(
            "games/game_description_attribution.html",
            {"description_attributions": [SimpleNamespace(name="apero.ru")]},
        )

        self.assertIn("описание взято с сайта apero.ru", html)

    def test_multiple_attributions_use_plural_site_word(self):
        html = render_to_string(
            "games/game_description_attribution.html",
            {
                "description_attributions": [
                    SimpleNamespace(name="apero.ru"),
                    SimpleNamespace(name="ifwiki.ru"),
                ]
            },
        )

        self.assertIn("описание взято с сайтов apero.ru, ifwiki.ru", html)

    def test_no_attributions_render_nothing(self):
        html = render_to_string(
            "games/game_description_attribution.html",
            {"description_attributions": []},
        )

        self.assertEqual(html.strip(), "")
