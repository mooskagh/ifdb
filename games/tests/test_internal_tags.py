from django.contrib.auth.models import AnonymousUser, Group
from django.test import RequestFactory, TestCase
from django.utils.timezone import now

from core.models import User
from curation.manual import store_manual_edit
from games.game_details import GameDetailsBuilder
from games.gameinfo import GameInfo, Tag
from games.models import Game, GameRevision, GameTag, GameTagCategory
from games.search import MakeSearch, SB_Tag
from games.views import BuildJsonGameInfo, tags


class InternalTagsTest(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.anon = AnonymousUser()
        self.user = User.objects.create_user(
            username="normal_user",
            email="user@example.com",
            password="secretpassword",
        )
        self.moder = User.objects.create_user(
            username="moder_user",
            email="moder@example.com",
            password="secretpassword",
        )
        moder_group = Group.objects.create(name="moder")
        self.moder.groups.add(moder_group)

        self.genre_cat, _ = GameTagCategory.objects.update_or_create(
            symbolic_id="genre",
            defaults={
                "name": "Жанр",
                "allow_new_tags": False,
                "is_internal": False,
                "order": 1,
            },
        )
        self.service_cat, _ = GameTagCategory.objects.update_or_create(
            symbolic_id="service",
            defaults={
                "name": "Служебный",
                "allow_new_tags": True,
                "is_internal": True,
                "order": 100,
            },
        )
        self.public_tag, _ = GameTag.objects.update_or_create(
            category=self.genre_cat,
            symbolic_id="adventure",
            defaults={"name": "Приключения"},
        )
        self.internal_tag, _ = GameTag.objects.update_or_create(
            category=self.service_cat,
            symbolic_id="needs_review",
            defaults={"name": "Нужна проверка"},
        )

        self.game = Game.objects.create(
            title="Test Game",
            state=Game.State.PUBLISHED,
            creation_time=now(),
        )
        self.game.tags.add(self.public_tag, self.internal_tag)

        # Initial published revision
        info = GameInfo(
            name="Test Game",
            tags=[
                Tag("genre", "adventure", self.public_tag.id, "Приключения"),
                Tag(
                    "service",
                    "needs_review",
                    self.internal_tag.id,
                    "Нужна проверка",
                ),
            ],
        )
        self.initial_rev = GameRevision.objects.create(
            game=self.game,
            created_at=now(),
            created_by=self.moder,
            origin=GameRevision.Origin.MANUAL_EDIT,
            status=GameRevision.Status.ACCEPTED,
            published_at=now(),
            published_by=self.moder,
            canonical_text=info.to_canonical(),
        )
        self.game.published_revision = self.initial_rev
        self.game.save(update_fields=["published_revision"])

    def test_game_details_hides_internal_tags_from_users(self) -> None:
        info = GameInfo.from_game(self.game)
        builder = GameDetailsBuilder(info)

        # Anonymous request
        anon_request = self.factory.get("/")
        anon_request.user = self.anon
        anon_details = builder.GetTagsForDetails(anon_request)
        anon_genre_tags = [t.name for t in anon_details.genres]
        anon_sec_tags = [
            t.name
            for _, tag_list in anon_details.secondary_properties
            for t in tag_list
        ]
        self.assertIn("Приключения", anon_genre_tags)
        self.assertNotIn("Нужна проверка", anon_sec_tags)

        # Normal user request
        user_request = self.factory.get("/")
        user_request.user = self.user
        user_details = builder.GetTagsForDetails(user_request)
        user_genre_tags = [t.name for t in user_details.genres]
        user_sec_tags = [
            t.name
            for _, tag_list in user_details.secondary_properties
            for t in tag_list
        ]
        self.assertIn("Приключения", user_genre_tags)
        self.assertNotIn("Нужна проверка", user_sec_tags)

        # Moderator request
        moder_request = self.factory.get("/")
        moder_request.user = self.moder
        moder_details = builder.GetTagsForDetails(moder_request)
        moder_genre_tags = [t.name for t in moder_details.genres]
        moder_sec_tags = [
            t.name
            for _, tag_list in moder_details.secondary_properties
            for t in tag_list
        ]
        self.assertIn("Приключения", moder_genre_tags)
        self.assertIn("Нужна проверка", moder_sec_tags)

    def test_editor_tags_view_excludes_internal_category_for_users(
        self,
    ) -> None:
        user_req = self.factory.get("/tags/")
        user_req.user = self.user
        user_res = tags(user_req)
        user_cat_ids = [c["id"] for c in user_res["categories"]]
        self.assertIn(self.genre_cat.id, user_cat_ids)
        self.assertNotIn(self.service_cat.id, user_cat_ids)

        moder_req = self.factory.get("/tags/")
        moder_req.user = self.moder
        moder_res = tags(moder_req)
        moder_cat_ids = [c["id"] for c in moder_res["categories"]]
        self.assertIn(self.genre_cat.id, moder_cat_ids)
        self.assertIn(self.service_cat.id, moder_cat_ids)

    def test_editor_build_json_gameinfo_excludes_internal_tags_for_users(
        self,
    ) -> None:
        user_req = self.factory.get("/json/gameinfo/")
        user_req.user = self.user
        user_info = BuildJsonGameInfo(user_req, self.game.id)
        tag_tuples = user_info["tags"]
        self.assertIn((self.genre_cat.id, self.public_tag.id), tag_tuples)
        self.assertNotIn(
            (self.service_cat.id, self.internal_tag.id), tag_tuples
        )

        moder_req = self.factory.get("/json/gameinfo/")
        moder_req.user = self.moder
        moder_info = BuildJsonGameInfo(moder_req, self.game.id)
        moder_tag_tuples = moder_info["tags"]
        self.assertIn(
            (self.genre_cat.id, self.public_tag.id), moder_tag_tuples
        )
        self.assertIn(
            (self.service_cat.id, self.internal_tag.id), moder_tag_tuples
        )

    def test_make_search_excludes_internal_categories_for_users(self) -> None:
        anon_search = MakeSearch(self.anon)
        anon_tag_cats = [
            bit.cat.id for bit in anon_search.bits if isinstance(bit, SB_Tag)
        ]
        self.assertIn(self.genre_cat.id, anon_tag_cats)
        self.assertNotIn(self.service_cat.id, anon_tag_cats)

        user_search = MakeSearch(self.user)
        user_tag_cats = [
            bit.cat.id for bit in user_search.bits if isinstance(bit, SB_Tag)
        ]
        self.assertIn(self.genre_cat.id, user_tag_cats)
        self.assertNotIn(self.service_cat.id, user_tag_cats)

        moder_search = MakeSearch(self.moder)
        moder_tag_cats = [
            bit.cat.id for bit in moder_search.bits if isinstance(bit, SB_Tag)
        ]
        self.assertIn(self.genre_cat.id, moder_tag_cats)
        self.assertIn(self.service_cat.id, moder_tag_cats)

    def test_user_edit_preserves_internal_tags(self) -> None:
        # User payload only has public tag (since user cannot see internal tag)
        user_payload = {
            "game_id": self.game.id,
            "title": "Updated Title by User",
            "tags": [(self.genre_cat.id, self.public_tag.id)],
            "authors": [],
            "links": [],
            "description_attributions": [],
        }
        rev = store_manual_edit(
            self.game, user_payload, self.user, apply=False
        )

        # Verify revision canonical text preserved the service tag
        self.assertIn("needs_review", rev.canonical_text)
        self.assertIn("adventure", rev.canonical_text)

        # Even if applied, game still has the internal tag
        self.game.publish_revision(rev, actor=self.moder)
        game_tag_ids = set(self.game.tags.values_list("id", flat=True))
        self.assertIn(self.internal_tag.id, game_tag_ids)
        self.assertIn(self.public_tag.id, game_tag_ids)

    def test_moderator_edit_can_remove_internal_tags(self) -> None:
        # Moderator explicitly sends payload without the internal tag
        moder_payload = {
            "game_id": self.game.id,
            "title": "Updated Title by Mod",
            "tags": [(self.genre_cat.id, self.public_tag.id)],
            "authors": [],
            "links": [],
            "description_attributions": [],
        }
        rev = store_manual_edit(
            self.game, moder_payload, self.moder, apply=True
        )

        # Service tag was removed by moderator
        self.assertNotIn("needs_review", rev.canonical_text)
        game_tag_ids = set(self.game.tags.values_list("id", flat=True))
        self.assertNotIn(self.internal_tag.id, game_tag_ids)
        self.assertIn(self.public_tag.id, game_tag_ids)
