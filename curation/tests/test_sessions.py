import uuid
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from games.models import Game
from play.models import Playable, PlaySegment, PlaySession

User = get_user_model()


class SessionListViewTest(TestCase):
    def setUp(self) -> None:
        self.admin = User.objects.create(
            username="admin",
            email="admin@example.com",
            is_superuser=True,
        )
        self.game = Game.objects.create(
            title="Test Quest",
            creation_time=timezone.now(),
        )
        self.playable = Playable.objects.create(
            slug="test-quest",
            game=self.game,
            template="instead",
            template_version="1.0",
        )

    def test_superuser_required(self) -> None:
        # Anonymous user
        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 302)

        # Regular user
        reg_user = User.objects.create(
            username="regular",
            email="regular@example.com",
            is_superuser=False,
        )
        self.client.force_login(reg_user)
        res2 = self.client.get("/curation/sessions/")
        self.assertEqual(res2.status_code, 302)

        # Superuser
        self.client.force_login(self.admin)
        res3 = self.client.get("/curation/sessions/")
        self.assertEqual(res3.status_code, 200)

    def test_sessions_empty_state(self) -> None:
        self.client.force_login(self.admin)
        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Игровых сессий не найдено.")
        self.assertContains(res, "Игровые сессии")

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_session_display_url_datetime_no_uuid(self) -> None:
        self.client.force_login(self.admin)
        session_uuid = uuid.uuid4()
        t_start = timezone.make_aware(datetime(2026, 9, 19, 10, 0, 0))
        t_end = timezone.make_aware(datetime(2026, 9, 19, 12, 1, 3))

        session = PlaySession.objects.create(
            play_session_id=session_uuid,
            playable=self.playable,
            started_at=t_start,
            last_seen_at=t_end,
        )
        PlaySegment.objects.create(
            play_session=session,
            state=PlaySegment.State.ACTIVE,
            started_at=t_start,
            last_seen_at=t_end,
            active_seconds=7263.0,
            ip_addr="192.168.1.50",
        )

        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 200)

        # URL and game title displayed
        self.assertContains(res, "test-quest.play.crem.xyz")
        self.assertContains(res, "Test Quest")

        # Start datetime and End datetime on separate lines
        self.assertContains(res, "2026-09-19 10:00:00")
        self.assertContains(res, "2026-09-19 12:01:03")

        # UUID should NOT be visible
        self.assertNotContains(res, str(session_uuid))

        # Durations formatted: 2:01:03 for active, :00 for zero idle/bg
        self.assertContains(res, "Играли:")
        self.assertContains(res, "2:01:03")
        self.assertContains(res, "Бездействовали:")
        self.assertContains(res, ":00")
        self.assertContains(res, "Неактивно:")

    def test_username_if_any_segment_has_user_else_ip(self) -> None:
        self.client.force_login(self.admin)
        player = User.objects.create(
            username="gamer_bob",
            email="bob@example.com",
        )

        now = timezone.now()

        # Session 1: Has segments with user in middle
        session1 = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(minutes=10),
        )
        PlaySegment.objects.create(
            play_session=session1,
            user=None,
            ip_addr="1.1.1.1",
            started_at=now,
            last_seen_at=now + timedelta(minutes=2),
        )
        PlaySegment.objects.create(
            play_session=session1,
            user=player,
            ip_addr="1.1.1.1",
            started_at=now + timedelta(minutes=2),
            last_seen_at=now + timedelta(minutes=5),
        )
        PlaySegment.objects.create(
            play_session=session1,
            user=None,
            ip_addr="1.1.1.2",
            started_at=now + timedelta(minutes=5),
            last_seen_at=now + timedelta(minutes=10),
        )

        # Session 2: No segment has user -> show last IP
        session2 = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(minutes=6),
        )
        PlaySegment.objects.create(
            play_session=session2,
            user=None,
            ip_addr="10.0.0.1",
            started_at=now,
            last_seen_at=now + timedelta(minutes=2),
        )
        PlaySegment.objects.create(
            play_session=session2,
            user=None,
            ip_addr="10.0.0.99",
            started_at=now + timedelta(minutes=2),
            last_seen_at=now + timedelta(minutes=6),
        )

        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 200)

        # Session 1 should display username "gamer_bob"
        self.assertContains(res, "gamer_bob")

        # Session 2 should display IP of last segment "10.0.0.99"
        self.assertContains(res, "10.0.0.99")

    def test_duration_aggregation_and_detailed_segments(self) -> None:
        self.client.force_login(self.admin)
        t0 = timezone.make_aware(datetime(2026, 9, 19, 14, 0, 0))

        session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=t0,
            last_seen_at=t0 + timedelta(seconds=7620),
        )
        # 1. Active: 7263s (2:01:03)
        PlaySegment.objects.create(
            play_session=session,
            state=PlaySegment.State.ACTIVE,
            started_at=t0,
            last_seen_at=t0 + timedelta(seconds=7263),
            active_seconds=7263.0,
            ip_addr="192.168.1.1",
        )
        # 2. Idle: 312s (05:12)
        PlaySegment.objects.create(
            play_session=session,
            state=PlaySegment.State.IDLE,
            started_at=t0 + timedelta(seconds=7263),
            last_seen_at=t0 + timedelta(seconds=7575),
            active_seconds=0.0,
            ip_addr="192.168.1.1",
        )
        # 3. Background: 45s (:45)
        PlaySegment.objects.create(
            play_session=session,
            state=PlaySegment.State.BACKGROUND,
            started_at=t0 + timedelta(seconds=7575),
            last_seen_at=t0 + timedelta(seconds=7620),
            active_seconds=0.0,
            ip_addr="192.168.1.1",
        )

        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 200)

        # Durations formatted with zero-hiding rules:
        # Active: 2h 1m 3s -> 2:01:03
        self.assertContains(res, "2:01:03")
        # Idle: 0h 5m 12s -> 05:12 (hours hidden)
        self.assertContains(res, "05:12")
        # Background: 0h 0m 45s -> :45 (hours and minutes hidden, colon kept)
        self.assertContains(res, ":45")

        # Segment breakdown table details
        self.assertContains(res, "Играли")
        self.assertContains(res, "Бездействовали")
        self.assertContains(res, "Неактивно")

    def test_search_filter(self) -> None:
        self.client.force_login(self.admin)
        now = timezone.now()
        game2 = Game.objects.create(
            title="Another Adventure",
            creation_time=now,
        )
        playable2 = Playable.objects.create(
            slug="another-adv",
            game=game2,
            template="instead",
            template_version="1.0",
        )

        s1 = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )
        PlaySegment.objects.create(
            play_session=s1,
            state=PlaySegment.State.ACTIVE,
            ip_addr="10.0.0.1",
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )

        s2 = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=playable2,
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )
        PlaySegment.objects.create(
            play_session=s2,
            state=PlaySegment.State.ACTIVE,
            ip_addr="10.0.0.2",
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )

        # Search by game title
        res = self.client.get("/curation/sessions/?q=Adventure")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "another-adv")
        self.assertNotContains(res, "test-quest")

        # Search by IP
        res_ip = self.client.get("/curation/sessions/?q=10.0.0.1")
        self.assertEqual(res_ip.status_code, 200)
        self.assertContains(res_ip, "test-quest")
        self.assertNotContains(res_ip, "another-adv")

    def test_ordering_by_last_seen_at_and_timestamp_pagination(self) -> None:
        self.client.force_login(self.admin)
        base_time = timezone.now()

        # Create 105 sessions with duration > 1 second
        sessions = [
            PlaySession(
                play_session_id=uuid.uuid4(),
                playable=self.playable,
                started_at=base_time - timedelta(minutes=i + 5),
                last_seen_at=base_time - timedelta(minutes=i),
            )
            for i in range(105)
        ]
        PlaySession.objects.bulk_create(sessions)

        # Page 1: 100 sessions
        res_p1 = self.client.get("/curation/sessions/")
        self.assertEqual(res_p1.status_code, 200)
        self.assertEqual(len(res_p1.context["sessions"]), 100)
        self.assertTrue(res_p1.context["has_next"])
        self.assertFalse(res_p1.context["has_before"])
        self.assertContains(res_p1, "Следующие 100")
        self.assertNotContains(res_p1, "В начало")

        # Check ordering: first session is newest
        first_session = res_p1.context["sessions"][0]["session"]
        self.assertEqual(first_session.last_seen_at, base_time)

        # The next_page_query contains before parameter
        next_query = res_p1.context["next_page_query"]
        self.assertIn("before=", next_query)

        # Page 2: remaining 5 sessions
        res_p2 = self.client.get(f"/curation/sessions/?{next_query}")
        self.assertEqual(res_p2.status_code, 200)
        self.assertEqual(len(res_p2.context["sessions"]), 5)
        self.assertFalse(res_p2.context["has_next"])
        self.assertTrue(res_p2.context["has_before"])
        self.assertContains(res_p2, "В начало")
        self.assertNotContains(res_p2, "Следующие 100")

    def test_empty_sessions_filter(self) -> None:
        self.client.force_login(self.admin)
        now = timezone.now()

        # Empty session (< 1s)
        empty_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now,
        )
        PlaySegment.objects.create(
            play_session=empty_session,
            ip_addr="1.2.3.4",
            started_at=now,
            last_seen_at=now,
        )

        # Non-empty session (>= 1s)
        normal_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )
        PlaySegment.objects.create(
            play_session=normal_session,
            ip_addr="5.6.7.8",
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )

        # By default: hide_empty is ON -> empty session is hidden
        res_default = self.client.get("/curation/sessions/")
        self.assertEqual(res_default.status_code, 200)
        self.assertContains(res_default, "5.6.7.8")
        self.assertNotContains(res_default, "1.2.3.4")

        # When hide_empty=0 -> empty session is shown
        res_show = self.client.get("/curation/sessions/?hide_empty=0")
        self.assertEqual(res_show.status_code, 200)
        self.assertContains(res_show, "1.2.3.4")
        self.assertContains(res_show, "5.6.7.8")

    def test_admin_sessions_filter(self) -> None:
        self.client.force_login(self.admin)
        now = timezone.now()
        regular_user = User.objects.create(
            username="player1", email="p1@example.com", is_superuser=False
        )

        # Admin session
        admin_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )
        PlaySegment.objects.create(
            play_session=admin_session,
            user=self.admin,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )

        # Regular user session
        user_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )
        PlaySegment.objects.create(
            play_session=user_session,
            user=regular_user,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )

        # By default: hide_admins is ON -> admin session is hidden
        res_default = self.client.get("/curation/sessions/")
        self.assertEqual(res_default.status_code, 200)
        self.assertContains(res_default, "player1")
        self.assertNotContains(res_default, 'title="admin"')

        # When hide_admins=0 -> admin session is shown
        res_show = self.client.get("/curation/sessions/?hide_admins=0")
        self.assertEqual(res_show.status_code, 200)
        self.assertContains(res_show, 'title="admin"')
        self.assertContains(res_show, "player1")

    def test_user_type_dropdown_filter(self) -> None:
        self.client.force_login(self.admin)
        now = timezone.now()
        regular_user = User.objects.create(
            username="player2", email="p2@example.com", is_superuser=False
        )

        # Logged-in user session
        logged_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )
        PlaySegment.objects.create(
            play_session=logged_session,
            user=regular_user,
            ip_addr="11.22.33.44",
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )

        # Anonymous session
        anon_session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )
        PlaySegment.objects.create(
            play_session=anon_session,
            user=None,
            ip_addr="99.88.77.66",
            started_at=now,
            last_seen_at=now + timedelta(seconds=5),
        )

        # user_type=all (default) -> both shown
        res_all = self.client.get("/curation/sessions/?user_type=all")
        self.assertContains(res_all, "player2")
        self.assertContains(res_all, "99.88.77.66")

        # user_type=logged_in -> only logged-in shown
        res_logged = self.client.get("/curation/sessions/?user_type=logged_in")
        self.assertContains(res_logged, "player2")
        self.assertNotContains(res_logged, "99.88.77.66")

        # user_type=anonymous -> only anonymous shown
        res_anon = self.client.get("/curation/sessions/?user_type=anonymous")
        self.assertNotContains(res_anon, "player2")
        self.assertContains(res_anon, "99.88.77.66")

    def test_game_and_moderation_links_and_mobile_wrap(self) -> None:
        self.client.force_login(self.admin)
        now = timezone.now()
        session = PlaySession.objects.create(
            play_session_id=uuid.uuid4(),
            playable=self.playable,
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )
        PlaySegment.objects.create(
            play_session=session,
            ip_addr="1.1.1.1",
            started_at=now,
            last_seen_at=now + timedelta(seconds=10),
        )

        res = self.client.get("/curation/sessions/")
        self.assertEqual(res.status_code, 200)

        # Check mobile wrapper is present
        self.assertContains(res, "curation-sessions-table-wrap")

        # Check game page link
        game_url = reverse("show_game", args=[self.game.pk])
        self.assertContains(res, f'href="{game_url}"')
        self.assertContains(res, self.game.title)

        # Check moderation page link
        moderation_url = reverse(
            "curation_history_detail", args=[self.game.pk]
        )
        self.assertContains(res, f'href="{moderation_url}"')
        self.assertContains(res, "(модерация)")
