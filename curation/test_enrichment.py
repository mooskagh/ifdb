from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import TestCase

from .gameinfo import GameInfo, GameUrl, Tag
from .models import EnrichmentRule, GenreMapping
from .passes import EnrichmentPass


def _enrich(info: GameInfo) -> GameInfo:
    EnrichmentPass().apply(SimpleNamespace(current=info), {})
    return info


def _slugs(info: GameInfo) -> set[str]:
    return {t.slug for t in info.tags if t.slug}


class DefaultRuleTests(TestCase):
    """Pass driven by the seeded default rules (initenrichment)."""

    @classmethod
    def setUpTestData(cls):
        call_command("initenrichment", stdout=StringIO())

    def test_inform_platform_adds_parser_and_os_tags(self):
        info = GameInfo(tags=[Tag("platform", None, None, "Inform 7")])
        _enrich(info)
        self.assertLessEqual(
            {"parser", "os_web", "os_win", "os_linux", "os_macos"},
            _slugs(info),
        )

    def test_qsp_with_play_online_adds_os_web(self):
        info = GameInfo(
            tags=[Tag("platform", None, None, "qsp")],
            urls=[GameUrl("play_online", None, None, "http://ex/play")],
        )
        _enrich(info)
        self.assertIn("os_web", _slugs(info))

    def test_urq_clones_download_to_interpreter(self):
        info = GameInfo(
            tags=[Tag("platform", None, None, "urqw")],
            urls=[
                GameUrl("download_direct", None, "My Game", "http://ex/g.qst")
            ],
        )
        _enrich(info)
        cloned = [u for u in info.urls if u.category == "play_in_interpreter"]
        self.assertEqual(len(cloned), 1)
        self.assertEqual(cloned[0].url, "http://ex/g.qst")
        self.assertTrue(cloned[0].description.startswith("Открыть в UrqW:"))

    def test_missing_language_adds_russian(self):
        info = GameInfo(tags=[Tag("platform", None, None, "inform")])
        _enrich(info)
        self.assertTrue(
            any(
                t.category == "language" and t.text == "русский"
                for t in info.tags
            )
        )

    def test_existing_language_is_not_overridden(self):
        info = GameInfo(tags=[Tag("language", None, None, "english")])
        _enrich(info)
        languages = [t.text for t in info.tags if t.category == "language"]
        self.assertEqual(languages, ["english"])

    def test_rerun_is_idempotent(self):
        info = GameInfo(
            tags=[Tag("platform", None, None, "urqw")],
            urls=[GameUrl("download_direct", None, "g", "http://ex/g.qst")],
        )
        once = _enrich(info).to_canonical()
        twice = _enrich(info).to_canonical()
        self.assertEqual(once, twice)


class GenreMappingTests(TestCase):
    """Built-in lowercase + tag->genre steps, no rules seeded."""

    @classmethod
    def setUpTestData(cls):
        GenreMapping.objects.create(
            tag="детектив", genre_slug="g_detective", replace=True
        )
        GenreMapping.objects.create(
            tag="космос", genre_slug="g_scifi", replace=False
        )

    def test_replace_rewrites_tag_to_genre(self):
        info = GameInfo(tags=[Tag("tag", None, None, "Детектив")])
        _enrich(info)
        self.assertEqual(len(info.tags), 1)
        tag = info.tags[0]
        self.assertEqual(
            (tag.category, tag.slug, tag.text), ("genre", "g_detective", None)
        )

    def test_non_replace_keeps_tag_and_appends_genre(self):
        info = GameInfo(tags=[Tag("tag", None, None, "Космос")])
        _enrich(info)
        kinds = {(t.category, t.slug, t.text) for t in info.tags}
        self.assertIn(("tag", None, "космос"), kinds)
        self.assertIn(("genre", "g_scifi", None), kinds)


class SandboxTests(TestCase):
    def test_condition_has_no_builtins(self):
        EnrichmentRule.objects.create(
            order=0, condition="len([]) == 0", action="add_tag('x')"
        )
        with self.assertRaises(NameError):
            _enrich(GameInfo())
