import uuid
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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
        self.assertContains(res, "Игровых сессий нет.")
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

        # Start datetime – End datetime (YYYY-MM-DD HH:MM:SS formats)
        self.assertContains(res, "2026-09-19 10:00:00 – 2026-09-19 12:01:03")

        # UUID should NOT be visible
        self.assertNotContains(res, str(session_uuid))

        # Durations formatted as 2:01:03
        self.assertContains(
            res,
            "Играли: 2:01:03, бездействовали 0:00:00, неактивно: 0:00:00",
        )

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
        # 2. Idle: 312s (0:05:12)
        PlaySegment.objects.create(
            play_session=session,
            state=PlaySegment.State.IDLE,
            started_at=t0 + timedelta(seconds=7263),
            last_seen_at=t0 + timedelta(seconds=7575),
            active_seconds=0.0,
            ip_addr="192.168.1.1",
        )
        # 3. Background: 45s (0:00:45)
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

        # Summary line
        self.assertContains(
            res,
            "Играли: 2:01:03, бездействовали 0:05:12, неактивно: 0:00:45",
        )

        # Segment breakdown table details
        self.assertContains(res, "2:01:03")
        self.assertContains(res, "0:05:12")
        self.assertContains(res, "0:00:45")
        self.assertContains(res, "Играли")
        self.assertContains(res, "Бездействовали")
        self.assertContains(res, "Неактивно")

    def test_ordering_by_last_seen_at_and_pagination(self) -> None:
        self.client.force_login(self.admin)
        base_time = timezone.now()

        # Create 105 sessions
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
        self.assertEqual(len(res_p1.context["page"].object_list), 100)
        self.assertContains(res_p1, "Страница 1 из 2")

        # Check that page 1 starts with the most recent last_seen_at
        first_session = res_p1.context["page"].object_list[0]
        self.assertEqual(first_session.last_seen_at, base_time)

        # Page 2: 5 sessions
        res_p2 = self.client.get("/curation/sessions/?page=2")
        self.assertEqual(res_p2.status_code, 200)
        self.assertEqual(len(res_p2.context["page"].object_list), 5)
        self.assertContains(res_p2, "Страница 2 из 2")
