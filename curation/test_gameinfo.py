import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from games.models import (
    URL,
    GameAuthor,
    GameDescriptionAttribution,
    GameTag,
    GameTagCategory,
    GameURL,
    Personality,
    PersonalityAlias,
    PersonalityAliasRedirect,
)

from .gameinfo import (
    Attribution,
    GameInfo,
    GameUrl,
    Person,
    Tag,
    merge,
    parse,
)


class GameInfoTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("initifdb", stdout=StringIO(), stderr=StringIO())

    def _seeded_info(self):
        """A GameInfo touching every entry kind, from seeded/created rows."""
        alias = PersonalityAlias.objects.create(name="John Doe")
        tag_cat = GameTagCategory.objects.get(symbolic_id="tag")
        db_tag = GameTag.objects.create(category=tag_cat, name="cool")
        url = URL.objects.create(
            original_url="http://example.com/game.zip",
            creation_date=timezone.now(),
        )
        attr = GameDescriptionAttribution.objects.create(name="apero.ru")
        return GameInfo(
            name="Неправильная сказка",
            date="2021-05-30",
            description="A *markdown* body.",
            personalities={
                "author": [Person(alias.id, ""), Person(None, "New artist")],
            },
            tags=[
                Tag("os", "os_win", None, None),
                Tag("tag", None, db_tag.id, None),
                Tag("tag", None, None, "fresh"),
            ],
            urls=[
                GameUrl("download_direct", url.id, "Скачать", None),
                GameUrl("poster", None, "Постер", "http://example.com/p.png"),
            ],
            attributions=[
                Attribution(attr.id, ""),
                Attribution(None, "itch.io"),
            ],
        )


class CanonicalRoundTripTest(GameInfoTestBase):
    def test_canonical_is_idempotent(self):
        _, canonical = self._seeded_info().save()
        reparsed = parse(canonical)
        # Re-canonicalizing parsed output is stable.
        self.assertEqual(reparsed.to_canonical(), canonical)
        # And parsing the stable output yields the same structure.
        self.assertEqual(parse(reparsed.to_canonical()), reparsed)

    def test_canonical_shape(self):
        canonical = self._seeded_info().to_canonical()
        self.assertTrue(canonical.startswith("---\n"))
        self.assertIn('- name: "Неправильная сказка"\n', canonical)
        self.assertIn('- release_date: "2021-05-30"\n', canonical)
        self.assertIn('  - "os_win"\n', canonical)
        self.assertRegex(
            canonical,
            r'  - \["download_direct", \d+\]  # "Скачать" "http://example\.com/game\.zip"\n',
        )
        self.assertTrue(canonical.endswith("---\nA *markdown* body."))

    def test_from_game_round_trips(self):
        game, canonical = self._seeded_info().save()
        rebuilt = GameInfo.from_game(game)
        self.assertEqual(
            rebuilt.to_canonical(), parse(canonical).to_canonical()
        )

    def test_slug_tags_sort_by_slug_not_id(self):
        fairy = GameTag.objects.get(symbolic_id="g_fairytale")
        kids = GameTag.objects.get(symbolic_id="g_kids")
        info = GameInfo(
            tags=[
                Tag("genre", "g_kids", kids.id, None),
                Tag("genre", "g_fairytale", fairy.id, None),
            ]
        )

        canonical = info.to_canonical()

        self.assertLess(
            canonical.index('  - "g_fairytale"'),
            canonical.index('  - "g_kids"'),
        )

    def test_empty_personality_role_is_ignored(self):
        info = GameInfo(
            personalities={
                None: [Person(None, "Nobody")],
                "author": [Person(None, "Alice")],
            }
        )

        canonical = info.to_canonical()

        self.assertIn("  - author:\n", canonical)
        self.assertIn('    - "Alice"\n', canonical)
        self.assertNotIn("Nobody", canonical)


class LooseParseTest(GameInfoTestBase):
    def test_unordered_plain_mapping_matches_canonical(self):
        alias = PersonalityAlias.objects.create(name="Jane")
        canonical = (
            "---\n"
            '- name: "Game"\n'
            "- personalities:\n"
            "  - author:\n"
            f"    - {alias.id}\n"
            "- tags:\n"
            '  - "os_win"\n'
            "---\n"
            "Body."
        )
        loose = (
            "---\n"
            "tags:\n"
            "  - os_win\n"
            "personalities:\n"
            "  author:\n"
            f"    - {alias.id}\n"
            'name: "Game"\n'
            "---\n"
            "Body."
        )
        self.assertEqual(parse(loose), parse(canonical))

    def test_text_addressed_references_resolve(self):
        alias = PersonalityAlias.objects.create(name="Resolved Person")
        GameDescriptionAttribution.objects.create(name="apero.ru")
        loose = (
            "---\n"
            "personalities:\n"
            "  author:\n"
            '    - "Resolved Person"\n'
            "attributions:\n"
            '  - "apero.ru"\n'
            "---\n"
        )
        info = parse(loose)
        self.assertEqual(info.personalities["author"][0].alias_id, alias.id)
        self.assertIsNotNone(info.attributions[0].attr_id)

    def test_person_redirect_resolves(self):
        alias = PersonalityAlias.objects.create(name="Canonical Name")
        PersonalityAliasRedirect.objects.create(
            name="Old Name", hidden_for=alias
        )

        info = parse(
            '---\n- personalities:\n  - author:\n    - "Old Name"\n---\n'
        )

        self.assertEqual(info.personalities["author"][0], Person(alias.id, ""))

    def test_text_tag_and_language_are_lowercased(self):
        info = parse(
            '---\n- tags:\n  - ["tag", "Детектив"]\n'
            '  - ["language", "Русский"]\n'
            '  - ["platform", "INSTEAD"]\n---\n'
        )

        self.assertEqual(
            info.tags,
            [
                Tag("tag", None, None, "детектив"),
                Tag("language", None, None, "русский"),
                Tag("platform", None, None, "INSTEAD"),
            ],
        )


class CanonicalizeTest(GameInfoTestBase):
    def test_resolves_existing_references_without_creating_new_ones(self):
        alias = PersonalityAlias.objects.create(name="Resolved Person")
        language_cat = GameTagCategory.objects.get(symbolic_id="language")
        language = GameTag.objects.create(
            category=language_cat, name="русский"
        )
        url = URL.objects.create(
            original_url="http://example.com/game",
            creation_date=timezone.now(),
        )
        attr = GameDescriptionAttribution.objects.create(name="ifwiki.ru")
        info = GameInfo(
            personalities={"author": [Person(None, "Resolved Person")]},
            tags=[Tag("language", None, None, "русский")],
            urls=[
                GameUrl("game_page", None, "Page", "http://example.com/game")
            ],
            attributions=[Attribution(None, "ifwiki.ru")],
        )

        info.canonicalize()

        self.assertEqual(info.personalities["author"], [Person(alias.id, "")])
        self.assertEqual(info.tags, [Tag("language", None, language.id, None)])
        self.assertEqual(
            info.urls,
            [GameUrl("game_page", url.id, "Page", "http://example.com/game")],
        )
        self.assertEqual(info.attributions, [Attribution(attr.id, "")])

    def test_deduplicates_after_resolving_existing_references(self):
        alias = PersonalityAlias.objects.create(name="Resolved Person")
        fantasy = GameTag.objects.get(symbolic_id="g_fantasy")
        url = URL.objects.create(
            original_url="http://rinform.org/game.zip",
            creation_date=timezone.now(),
        )
        attr = GameDescriptionAttribution.objects.create(name="ifwiki.ru")
        info = GameInfo(
            personalities={
                "author": [
                    Person(alias.id, ""),
                    Person(None, "Resolved Person"),
                ]
            },
            tags=[
                Tag("genre", fantasy.symbolic_id, fantasy.id, None),
                Tag("genre", fantasy.symbolic_id, None, None),
            ],
            urls=[
                GameUrl("download_direct", url.id, "Скачать", None),
                GameUrl(
                    "download_direct",
                    None,
                    "Скачать",
                    "http://rinform.stormway.ru/game.zip",
                ),
            ],
            attributions=[
                Attribution(attr.id, ""),
                Attribution(None, "ifwiki.ru"),
            ],
        )

        info.canonicalize()

        self.assertEqual(
            info.personalities, {"author": [Person(alias.id, "")]}
        )
        self.assertEqual(
            info.tags, [Tag("genre", fantasy.symbolic_id, fantasy.id, None)]
        )
        self.assertEqual(
            info.urls,
            [GameUrl("download_direct", url.id, "Скачать", None)],
        )
        self.assertEqual(info.attributions, [Attribution(attr.id, "")])


class FromImporterDictTest(GameInfoTestBase):
    def test_scalar_fields(self):
        info = GameInfo.from_importer_dict({
            "title": "Игра",
            "desc": "A *markdown* body.",
            "release_date": datetime.date(2020, 1, 2),
        })
        self.assertEqual(info.name, "Игра")
        self.assertEqual(info.description, "A *markdown* body.")
        self.assertEqual(info.date, "2020-01-02")

    def test_authors_role_slug(self):
        info = GameInfo.from_importer_dict({
            "authors": [
                {"role_slug": "author", "name": "Alice"},
                {"role_slug": "author", "name": "Bob"},
                {"role_slug": "artist", "name": "Carol"},
            ]
        })
        self.assertEqual(
            [p.name for p in info.personalities["author"]], ["Alice", "Bob"]
        )
        self.assertEqual(info.personalities["artist"][0].name, "Carol")
        # Ids are left unresolved; names stay as text.
        self.assertIsNone(info.personalities["author"][0].alias_id)

    def test_authors_role_title_fallback(self):
        # No role_slug: resolve the human title via GameAuthorRole.
        info = GameInfo.from_importer_dict({
            "authors": [{"role": "Художник", "name": "Dave"}]
        })
        self.assertEqual(info.personalities["artist"][0].name, "Dave")

    def test_tags_slug_vs_category(self):
        info = GameInfo.from_importer_dict({
            "tags": [
                {"tag_slug": "released"},
                {"cat_slug": "platform", "tag": "INSTEAD"},
                # tag_slug wins even when a category is also present.
                {"cat_slug": "x", "tag": "y", "tag_slug": "ifwiki_featured"},
            ]
        })
        self.assertEqual(info.tags[0], Tag("", "released", None, None))
        self.assertEqual(info.tags[1], Tag("platform", None, None, "INSTEAD"))
        self.assertEqual(info.tags[2], Tag("", "ifwiki_featured", None, None))

    def test_imported_tags_lowercase_only_tag_and_language(self):
        info = GameInfo.from_importer_dict({
            "tags": [
                {"cat_slug": "tag", "tag": "Детектив"},
                {"cat_slug": "language", "tag": "Русский"},
                {"cat_slug": "platform", "tag": "INSTEAD"},
                {"cat_slug": "competition", "tag": "ЛОК-2020"},
                {"cat_slug": "ifid", "tag": "12345-ABCDE"},
            ]
        })

        self.assertEqual(
            info.tags,
            [
                Tag("tag", None, None, "детектив"),
                Tag("language", None, None, "русский"),
                Tag("platform", None, None, "INSTEAD"),
                Tag("competition", None, None, "ЛОК-2020"),
                Tag("ifid", None, None, "12345-ABCDE"),
            ],
        )

    def test_urls_and_falsy_urlcat_skipped(self):
        info = GameInfo.from_importer_dict({
            "urls": [
                {"urlcat_slug": "game_page", "description": "d", "url": "u1"},
                {"urlcat_slug": "", "description": "x", "url": "u2"},
                {"urlcat_slug": None, "url": "u3"},
            ]
        })
        self.assertEqual(info.urls, [GameUrl("game_page", None, "d", "u1")])

    def test_attributions(self):
        info = GameInfo.from_importer_dict({
            "description_attributions": ["apero.ru", "ifwiki.ru"]
        })
        self.assertEqual(
            info.attributions,
            [Attribution(None, "apero.ru"), Attribution(None, "ifwiki.ru")],
        )

    def test_empty_dict_is_empty_gameinfo(self):
        self.assertEqual(GameInfo.from_importer_dict({}), GameInfo())


class MergeTest(GameInfoTestBase):
    def test_union_dedup_and_scalars(self):
        base = GameInfo(
            name="Base",
            description="A",
            tags=[Tag("os", "os_win", None, None)],
            attributions=[Attribution(None, "shared")],
        )
        incoming = GameInfo(
            name="Incoming",
            date="2020-01-01",
            description="B",
            tags=[
                Tag("os", "os_win", None, None),  # dup, dropped
                Tag("os", "os_linux", None, None),
            ],
            attributions=[
                Attribution(None, "shared"),
                Attribution(None, "new"),
            ],
        )
        result = merge(base, incoming)
        self.assertEqual(result.name, "Base")  # first non-empty wins
        self.assertEqual(result.date, "2020-01-01")  # filled from incoming
        self.assertEqual(result.description, "A\n\n---\n\nB")
        self.assertEqual([t.slug for t in result.tags], ["os_win", "os_linux"])
        self.assertEqual(
            [a.name for a in result.attributions], ["shared", "new"]
        )

    def test_dedups_resolved_and_imported_slug_tags(self):
        fairy = GameTag.objects.get(symbolic_id="g_fairytale")
        kids = GameTag.objects.get(symbolic_id="g_kids")
        base = GameInfo(
            tags=[
                Tag("genre", "g_fairytale", fairy.id, None),
                Tag("genre", "g_kids", kids.id, None),
            ]
        )
        incoming = GameInfo.from_importer_dict({
            "tags": [
                {"tag_slug": "g_fairytale"},
                {"tag_slug": "g_kids"},
            ]
        })

        result = merge(base, incoming)

        self.assertEqual(
            [t.slug for t in result.tags], ["g_fairytale", "g_kids"]
        )


class SaveTest(GameInfoTestBase):
    def test_create_resolves_new_entries_and_resave_is_noop(self):
        game, canonical = self._seeded_info().save()

        game.refresh_from_db()
        self.assertEqual(game.title, "Неправильная сказка")
        self.assertEqual(game.release_date.isoformat(), "2021-05-30")
        self.assertEqual(game.tags.count(), 3)
        self.assertEqual(game.gameauthor_set.count(), 2)
        self.assertEqual(game.gameurl_set.count(), 2)
        self.assertEqual(game.description_attributions.count(), 2)
        self.assertEqual(
            Personality.objects.get(personalityalias__name="New artist").name,
            "New artist",
        )

        # The new "fresh" tag was created and resolved to an id in the doc:
        # it appears as a DB entry, not as a new-entry ["tag", "fresh"] form.
        fresh = GameTag.objects.get(name="fresh")
        self.assertIn(f'["tag", {fresh.id}]', canonical)
        self.assertNotIn('["tag", "fresh"]', canonical)

        # Re-saving the canonical document changes nothing.
        before = (
            GameTag.objects.count(),
            PersonalityAlias.objects.count(),
            GameURL.objects.count(),
            GameAuthor.objects.count(),
        )
        parse(canonical).save(game)
        after = (
            GameTag.objects.count(),
            PersonalityAlias.objects.count(),
            GameURL.objects.count(),
            GameAuthor.objects.count(),
        )
        self.assertEqual(before, after)
        game.refresh_from_db()
        self.assertEqual(game.tags.count(), 3)
        self.assertEqual(game.gameurl_set.count(), 2)

    def test_update_adds_and_removes(self):
        game, _ = self._seeded_info().save()
        # Drop os_win, keep the rest, add os_linux.
        updated = parse('---\n- tags:\n  - "os_linux"\n---\n')
        updated.save(game)
        slugs = set(
            game.tags.exclude(symbolic_id=None).values_list(
                "symbolic_id", flat=True
            )
        )
        self.assertIn("os_linux", slugs)
        self.assertNotIn("os_win", slugs)
