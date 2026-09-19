import json
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import User
from games.models import (
    Game,
    GameAuthor,
    GameAuthorRole,
    Personality,
    PersonalityAlias,
)
from play.models import Playable, PlaySegment, PlaySession


class TelemetryAPITests(TestCase):
    def setUp(self) -> None:
        self.game = Game.objects.create(
            title="Telemetry Quest",
            state=Game.State.PUBLISHED,
            creation_time=timezone.now(),
        )
        self.playable = Playable.objects.create(
            slug="telemetry-quest",
            game=self.game,
            template="instead_em",
            template_version="3.5.2",
            player_name="INSTEAD",
            player_url="https://instead3.hugeping.ru/",
            state=Playable.State.READY,
        )
        role, _ = GameAuthorRole.objects.get_or_create(
            symbolic_id="author", defaults={"title": "Author"}
        )
        pers = Personality.objects.create()
        alias = PersonalityAlias.objects.create(
            personality=pers, name="Alice Author"
        )
        GameAuthor.objects.create(game=self.game, author=alias, role=role)

        self.user = User.objects.create_user(
            username="gamer", email="gamer@example.com", password="password"
        )
        self.session_id = uuid.uuid4()

    def test_game_loaded_creates_session_and_segment(self) -> None:
        payload = {
            "event": "game_loaded",
            "play_session_id": str(self.session_id),
            "playable_id": self.playable.pk,
            "state": "active",
        }
        response = self.client.post(
            "/play/telemetry/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.42",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["play_session_id"], str(self.session_id))
        self.assertEqual(data["playable_id"], self.playable.pk)
        self.assertEqual(data["game_name"], "Telemetry Quest")
        self.assertEqual(data["authors"], "Alice Author")
        self.assertEqual(
            data["game_url"], f"http://testserver/game/{self.game.pk}/"
        )
        self.assertEqual(data["player_name"], "INSTEAD")
        self.assertEqual(data["player_url"], "https://instead3.hugeping.ru/")

        # Check DB session
        session = PlaySession.objects.get(play_session_id=self.session_id)
        self.assertEqual(session.playable, self.playable)

        # Check DB segment
        segments = list(PlaySegment.objects.filter(play_session=session))
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual(segment.state, PlaySegment.State.ACTIVE)
        self.assertEqual(segment.ip_addr, "198.51.100.42")
        self.assertIsNone(segment.user)
        self.assertEqual(segment.active_seconds, 0)

    def test_game_loaded_with_slug_and_authenticated_user(self) -> None:
        self.client.force_login(self.user)
        payload = {
            "event": "game_loaded",
            "play_session_id": str(self.session_id),
            "playable_id": "telemetry-quest",
        }
        response = self.client.post(
            "/play/telemetry/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_FORWARDED_FOR="203.0.113.19, 10.0.0.1",
        )
        self.assertEqual(response.status_code, 200)

        segment = PlaySegment.objects.get(
            play_session__play_session_id=self.session_id
        )
        self.assertEqual(segment.user, self.user)
        self.assertEqual(segment.ip_addr, "203.0.113.19")
        self.assertEqual(segment.state, PlaySegment.State.ACTIVE)
        self.assertIsNotNone(segment.django_session_key)

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_game_loaded_with_game_urls(self) -> None:
        test_urls = [
            "https://telemetry-quest.play.crem.xyz/play/index.html?v=1",
            "http://telemetry-quest.play.crem.xyz:8000/",
            "telemetry-quest.play.crem.xyz",
            "telemetry-quest.play.crem.xyz/subpath",
            "http://telemetry-quest.localhost:8000",
        ]
        for url in test_urls:
            session_id = uuid.uuid4()
            payload = {
                "event": "game_loaded",
                "play_session_id": str(session_id),
                "playable_id": url,
            }
            res = self.client.post(
                "/play/telemetry/",
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(
                res.status_code, 200, f"Failed for playable_id URL: {url}"
            )
            data = res.json()
            self.assertEqual(data["playable_id"], self.playable.pk)
            session = PlaySession.objects.get(play_session_id=session_id)
            self.assertEqual(session.playable, self.playable)

    def test_game_loaded_idempotency(self) -> None:
        payload = {
            "event": "game_loaded",
            "play_session_id": str(self.session_id),
            "playable_id": self.playable.pk,
        }
        res1 = self.client.post(
            "/play/telemetry/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res1.status_code, 200)

        res2 = self.client.post(
            "/play/telemetry/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 200)

        self.assertEqual(
            PlaySession.objects.filter(
                play_session_id=self.session_id
            ).count(),
            1,
        )
        self.assertEqual(
            PlaySegment.objects.filter(
                play_session__play_session_id=self.session_id
            ).count(),
            1,
        )

    def test_game_loaded_validation_errors(self) -> None:
        # Missing play_session_id
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

        # Invalid UUID
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": "not-a-uuid",
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

        # Non-existent playable
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(uuid.uuid4()),
                "playable_id": 999999,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_ping_collapsing_same_parameters(self) -> None:
        # Load game first
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(self.session_id),
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )

        # Ping 1: 60 seconds elapsed
        ping_payload = {
            "event": "ping",
            "play_session_id": str(self.session_id),
            "state": "active",
            "seconds_since_last_ping": 60,
        }
        res1 = self.client.post(
            "/play/telemetry/",
            data=json.dumps(ping_payload),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )
        self.assertEqual(res1.status_code, 200)

        segment = PlaySegment.objects.get(
            play_session__play_session_id=self.session_id
        )
        self.assertEqual(segment.active_seconds, 60)

        # Ping 2: another 60 seconds elapsed with same params
        res2 = self.client.post(
            "/play/telemetry/",
            data=json.dumps(ping_payload),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )
        self.assertEqual(res2.status_code, 200)

        # Should still be 1 segment, with 120 active_seconds
        segments = list(
            PlaySegment.objects.filter(
                play_session__play_session_id=self.session_id
            )
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].active_seconds, 120)

    def test_ping_state_transition_attributes_time_to_previous_segment(
        self,
    ) -> None:
        # 1. Game loaded
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(self.session_id),
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )

        # 2. Ping active (60s)
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "active",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )

        # 3. State transition to IDLE with 60s elapsed
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "idle",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )

        segments = list(
            PlaySegment.objects.filter(
                play_session__play_session_id=self.session_id
            ).order_by("started_at", "id")
        )
        self.assertEqual(len(segments), 2)
        # Previous active segment should have accumulated the 60s
        self.assertEqual(segments[0].state, PlaySegment.State.ACTIVE)
        self.assertEqual(segments[0].active_seconds, 120)

        # New segment is IDLE with 0 active seconds
        self.assertEqual(segments[1].state, PlaySegment.State.IDLE)
        self.assertEqual(segments[1].active_seconds, 0)

        # 4. Another ping while IDLE (60s)
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "idle",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )
        segments = list(
            PlaySegment.objects.filter(
                play_session__play_session_id=self.session_id
            ).order_by("started_at", "id")
        )
        self.assertEqual(len(segments), 2)
        # IDLE segment collapses and active_seconds remains 0
        self.assertEqual(segments[1].active_seconds, 0)

    def test_ping_inactivity_gap_splits_segment(self) -> None:
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(self.session_id),
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )

        segment = PlaySegment.objects.get(
            play_session__play_session_id=self.session_id
        )
        # Simulate last seen 10 minutes ago (gap > 300s)
        segment.last_seen_at = timezone.now() - timedelta(seconds=600)
        segment.save(update_fields=["last_seen_at"])

        # Send ping after waking from hibernation
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "active",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
            REMOTE_ADDR="198.51.100.1",
        )
        self.assertEqual(res.status_code, 200)

        # Should split into two segments due to inactivity gap
        segments = list(
            PlaySegment.objects.filter(
                play_session__play_session_id=self.session_id
            ).order_by("started_at", "id")
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[1].active_seconds, 60)

    def test_ping_validation_errors(self) -> None:
        # Non-existent session
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(uuid.uuid4()),
                "state": "active",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

        # Invalid state
        self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(self.session_id),
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
        )
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "invalid_state",
                "seconds_since_last_ping": 60,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

        # Missing seconds_since_last_ping
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "active",
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

        # Negative seconds
        res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "ping",
                "play_session_id": str(self.session_id),
                "state": "active",
                "seconds_since_last_ping": -10,
            }),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    @override_settings(PLAYABLE_BASE_DOMAIN="play.crem.xyz")
    def test_cors_options_and_post_headers(self) -> None:
        # OPTIONS preflight from allowed origin
        res = self.client.options(
            "/play/telemetry/",
            HTTP_ORIGIN="https://telemetry-quest.play.crem.xyz",
        )
        self.assertEqual(res.status_code, 204)
        self.assertEqual(
            res.headers["Access-Control-Allow-Origin"],
            "https://telemetry-quest.play.crem.xyz",
        )
        self.assertEqual(
            res.headers["Access-Control-Allow-Credentials"], "true"
        )
        self.assertIn("POST", res.headers["Access-Control-Allow-Methods"])

        # POST request from allowed origin
        post_res = self.client.post(
            "/play/telemetry/",
            data=json.dumps({
                "event": "game_loaded",
                "play_session_id": str(self.session_id),
                "playable_id": self.playable.pk,
            }),
            content_type="application/json",
            HTTP_ORIGIN="https://telemetry-quest.play.crem.xyz",
        )
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(
            post_res.headers["Access-Control-Allow-Origin"],
            "https://telemetry-quest.play.crem.xyz",
        )

        # Disallowed origin does not get CORS headers
        other_origin_res = self.client.options(
            "/play/telemetry/",
            HTTP_ORIGIN="https://evil.com",
        )
        self.assertEqual(other_origin_res.status_code, 204)
        self.assertNotIn(
            "Access-Control-Allow-Origin", other_origin_res.headers
        )

    def test_method_not_allowed(self) -> None:
        res = self.client.get("/play/telemetry/")
        self.assertEqual(res.status_code, 405)
