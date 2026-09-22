from django.test import TestCase
from django.utils.timezone import now

from core.models import User
from curation.merge import merge_game_into_game
from games.models import URL, Game, GameURL, GameURLCategory
from play.models import Playable


class MergePlayablesTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="merge_curator",
            email="curator@example.com",
            password="secretpassword",
        )
        self.cat = GameURLCategory.objects.create(
            symbolic_id="playable_game", title="Playable game"
        )
        self.source = Game.objects.create(
            title="Source", state=Game.State.PUBLISHED, creation_time=now()
        )
        self.target = Game.objects.create(
            title="Target", state=Game.State.PUBLISHED, creation_time=now()
        )

    def test_merge_transfers_unique_and_duplicate_pinned_urls(self) -> None:
        # Unique URL on source
        u1 = URL.objects.create(
            original_url="https://example.com/u1", creation_date=now()
        )
        gu1 = GameURL.objects.create(
            game=self.source, category=self.cat, url=u1
        )
        p1 = Playable.objects.create(
            game=self.source,
            game_url=gu1,
            slug="p1",
            template="p",
            template_version="1",
        )

        # Duplicate URL on both source and target
        u2 = URL.objects.create(
            original_url="https://example.com/u2", creation_date=now()
        )
        gu2_src = GameURL.objects.create(
            game=self.source, category=self.cat, url=u2
        )
        gu2_tgt = GameURL.objects.create(
            game=self.target, category=self.cat, url=u2
        )
        p2 = Playable.objects.create(
            game=self.source,
            game_url=gu2_src,
            slug="p2",
            template="p",
            template_version="1",
        )

        # Unlinked playable
        p3 = Playable.objects.create(
            game=self.source,
            game_url=None,
            slug="p3",
            template="p",
            template_version="1",
        )

        merge_game_into_game(
            target_game=self.target,
            source_game=self.source,
            actor=self.user,
            remap_contests=False,
        )

        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()
        self.assertEqual(p1.game_id, self.target.id)
        self.assertEqual(p1.game_url_id, gu1.id)
        self.assertEqual(p2.game_id, self.target.id)
        self.assertEqual(p2.game_url_id, gu2_tgt.id)
        self.assertEqual(p3.game_id, self.target.id)
        self.assertFalse(self.source.playable_set.exists())
        self.assertEqual(self.target.playable_set.count(), 3)
