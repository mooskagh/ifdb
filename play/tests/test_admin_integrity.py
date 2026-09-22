from django.contrib.admin.sites import site
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils.timezone import now

from core.models import User
from games.admin import GameURLAdmin, InlineGameURLAdmin
from games.models import URL, Game, GameURL, GameURLCategory
from play.admin import PlayableAdmin
from play.models import Playable
from play.services import format_pinned_url_error


class AdminIntegrityTest(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(
            username="admin_integ",
            email="admin_integ@example.com",
            password="secretpassword",
        )
        self.game1 = Game.objects.create(
            title="Game One", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.game2 = Game.objects.create(
            title="Game Two", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.cat = GameURLCategory.objects.create(
            symbolic_id="playable_game", title="Playable game"
        )
        self.url1 = URL.objects.create(
            original_url="https://example.com/play1", creation_date=now()
        )
        self.game_url1 = GameURL.objects.create(
            game=self.game1, category=self.cat, url=self.url1
        )
        self.request = self.factory.get("/")
        self.request.user = self.superuser
        SessionMiddleware(lambda req: HttpResponse()).process_request(
            self.request
        )
        self.request.session.save()
        MessageMiddleware(lambda req: HttpResponse()).process_request(
            self.request
        )

    def _create_playable(
        self, game: Game, game_url: GameURL | None = None, slug: str = "play-1"
    ) -> Playable:
        return Playable.objects.create(
            game=game,
            game_url=game_url,
            slug=slug,
            template="parchment",
            template_version="1",
        )

    def test_playable_admin_form_validation_cross_game_fails(self) -> None:
        admin_instance = PlayableAdmin(Playable, site)
        form_class = admin_instance.get_form(self.request)
        form = form_class(
            data={
                "game": self.game2.id,
                "game_url": self.game_url1.id,
                "slug": "test-cross",
                "template": "parchment",
                "template_version": "1",
                "state": Playable.State.PENDING,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("game_url", form.errors)
        self.assertIn(
            "belongs to a different game", str(form.errors["game_url"])
        )

    def test_inline_game_url_formset_blocks_pinned_deletion(self) -> None:
        self._create_playable(self.game1, self.game_url1, slug="pinned-play")
        formset_class = InlineGameURLAdmin(Game, site).get_formset(
            self.request
        )
        prefix = "gameurl_set"
        data = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.game_url1.id),
            f"{prefix}-0-game": str(self.game1.id),
            f"{prefix}-0-url": str(self.game_url1.url_id),
            f"{prefix}-0-category": str(self.game_url1.category_id),
            f"{prefix}-0-description": "",
            f"{prefix}-0-DELETE": "on",
        }
        formset = formset_class(data=data, instance=self.game1, prefix=prefix)
        self.assertFalse(formset.is_valid())
        self.assertIn(
            format_pinned_url_error(self.game_url1),
            str(formset.non_form_errors()),
        )

    def test_inline_game_url_formset_allows_unpinned_deletion(self) -> None:
        formset_class = InlineGameURLAdmin(Game, site).get_formset(
            self.request
        )
        prefix = "gameurl_set"
        data = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(self.game_url1.id),
            f"{prefix}-0-game": str(self.game1.id),
            f"{prefix}-0-url": str(self.game_url1.url_id),
            f"{prefix}-0-category": str(self.game_url1.category_id),
            f"{prefix}-0-description": "",
            f"{prefix}-0-DELETE": "on",
        }
        formset = formset_class(data=data, instance=self.game1, prefix=prefix)
        self.assertTrue(formset.is_valid())

    def test_game_url_admin_delete_view_blocks_pinned(self) -> None:
        self._create_playable(self.game1, self.game_url1, slug="pinned-view")
        self.client.force_login(self.superuser)
        url = reverse("admin:games_gameurl_delete", args=[self.game_url1.id])
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        messages_list = list(get_messages(response.wsgi_request))
        self.assertTrue(
            any(
                format_pinned_url_error(self.game_url1) in str(m)
                for m in messages_list
            )
        )
        self.assertTrue(GameURL.objects.filter(pk=self.game_url1.id).exists())

    def test_game_url_admin_delete_queryset_protects_pinned(self) -> None:
        self._create_playable(self.game1, self.game_url1, slug="pinned-qs")
        unpinned_url = URL.objects.create(
            original_url="https://example.com/unpinned", creation_date=now()
        )
        game_url_unpinned = GameURL.objects.create(
            game=self.game1, category=self.cat, url=unpinned_url
        )

        admin_instance = GameURLAdmin(GameURL, site)
        admin_instance.delete_queryset(
            self.request,
            GameURL.objects.filter(
                id__in=[self.game_url1.id, game_url_unpinned.id]
            ),
        )

        self.assertTrue(GameURL.objects.filter(pk=self.game_url1.id).exists())
        self.assertFalse(
            GameURL.objects.filter(pk=game_url_unpinned.id).exists()
        )
