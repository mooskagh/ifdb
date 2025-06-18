from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch


class MultiSiteUrlTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_show_competition_reverse_failure_on_kontigr(self):
        """Test show_competition reverse fails on kontigr for non-kontigr"""
        with override_settings(ROOT_URLCONF="kontigr.urls"):
            # This should fail because zok-2013 is not in kontigr URL patterns
            with self.assertRaises(NoReverseMatch):
                reverse(
                    "show_competition", kwargs={"slug": "zok-2013", "doc": ""}
                )

    def test_show_competition_reverse_success_on_main_site(self):
        """Test that show_competition reverse works on main site"""
        with override_settings(ROOT_URLCONF="ifdb.urls"):
            # This should work because main site has the general pattern
            url = reverse(
                "show_competition", kwargs={"slug": "zok-2013", "doc": ""}
            )
            self.assertEqual(url, "/jam/zok-2013/")

    def test_safe_url_template_tag(self):
        """Test that safe_url template tag handles NoReverseMatch gracefully"""
        from django.template import Context, Template

        # Test with valid URL
        with override_settings(ROOT_URLCONF="ifdb.urls"):
            template = Template(
                "{% load tags %}"
                "{% safe_url 'show_competition' slug='test-slug' doc='' %}"
            )
            result = template.render(Context({}))
            self.assertEqual(result, "/jam/test-slug/")

        # Test with invalid URL
        with override_settings(ROOT_URLCONF="kontigr.urls"):
            template = Template(
                "{% load tags %}"
                "{% safe_url 'show_competition' slug='invalid-slug' doc='' %}"
            )
            result = template.render(Context({}))
            self.assertEqual(result, "")  # Should return empty string for None

    def test_game_template_rendering_with_safe_url(self):
        """Test that game template renders without error using safe_url"""
        from django.template import Context, Template

        # Mock competition data that would cause NoReverseMatch
        competitions = [
            {
                "slug": "zok-2013",
                "title": "ZOK 2013",
                "nomination": "Test Nomination",
                "head": {"primary": "1", "secondary": "место"},
            }
        ]

        template_content = """
        {% load tags %}
        {% for x in competitions %}
            {% safe_url 'show_competition' slug=x.slug doc='' as url %}
            {% if url %}
                <a href="{{ url }}" class="game-banner">{{ x.title }}</a>
            {% else %}
                <div class="game-banner game-banner-disabled">
                    {{ x.title }}
                </div>
            {% endif %}
        {% endfor %}
        """

        template = Template(template_content)

        # Test with kontigr URLs (should render disabled banner)
        with override_settings(ROOT_URLCONF="kontigr.urls"):
            result = template.render(Context({"competitions": competitions}))
            self.assertIn("game-banner-disabled", result)
            self.assertIn("ZOK 2013", result)
            self.assertNotIn("<a href=", result)

        # Test with main site URLs (should render link)
        with override_settings(ROOT_URLCONF="ifdb.urls"):
            result = template.render(Context({"competitions": competitions}))
            self.assertIn('<a href="/jam/zok-2013/"', result)
            self.assertIn("ZOK 2013", result)
