from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils.timezone import now

from curation.models import LLMModel, LlmTrajectory, LlmWorkflow
from games.models import Game
from play.domain import (
    check_suggested_names,
    generate_playable_domain,
    is_domain_busy,
    is_valid_domain_slug,
)
from play.models import Playable


class TestDomainValidation(TestCase):
    def test_is_valid_domain_slug(self) -> None:
        self.assertTrue(is_valid_domain_slug("game"))
        self.assertTrue(is_valid_domain_slug("my-game"))
        self.assertTrue(is_valid_domain_slug("game-123"))
        self.assertTrue(is_valid_domain_slug("x"))

        self.assertFalse(is_valid_domain_slug(""))
        self.assertFalse(is_valid_domain_slug("Game"))
        self.assertFalse(is_valid_domain_slug("-game"))
        self.assertFalse(is_valid_domain_slug("game-"))
        self.assertFalse(is_valid_domain_slug("my--game"))
        self.assertFalse(is_valid_domain_slug("game.com"))
        self.assertFalse(is_valid_domain_slug("game_1"))
        self.assertFalse(is_valid_domain_slug("a" * 64))

    def test_is_domain_busy_reserved_and_format(self) -> None:
        busy, reason = is_domain_busy("www")
        self.assertTrue(busy)
        self.assertIn("reserved", reason)

        busy, reason = is_domain_busy("play")
        self.assertTrue(busy)
        self.assertIn("reserved", reason)

        busy, reason = is_domain_busy("INVALID_NAME")
        self.assertTrue(busy)
        self.assertIn("Invalid format", reason)

    def test_is_domain_busy_existing_playable(self) -> None:
        game = Game.objects.create(title="Game A", creation_time=now())
        p1 = Playable.objects.create(
            game=game,
            template="instead_em",
            template_version="1.0",
            slug="taken-slug",
        )

        busy, reason = is_domain_busy("taken-slug")
        self.assertTrue(busy)
        self.assertIn("already in use", reason)

        # Excluding current_playable_pk makes it not busy for itself
        busy, _ = is_domain_busy("taken-slug", current_playable_pk=p1.pk)
        self.assertFalse(busy)

        busy, _ = is_domain_busy("available-slug")
        self.assertFalse(busy)


class TestDomainTool(TestCase):
    def test_check_suggested_names(self) -> None:
        game = Game.objects.create(title="Game B", creation_time=now())
        Playable.objects.create(
            game=game,
            template="instead_em",
            template_version="1.0",
            slug="existing-game",
        )

        payload, selected = check_suggested_names([
            "www",
            "existing-game",
            "fresh-adventure",
            "another-adventure",
        ])

        self.assertEqual(selected, "fresh-adventure")
        self.assertFalse(payload["results"]["www"]["available"])
        self.assertFalse(payload["results"]["existing-game"]["available"])
        self.assertTrue(payload["results"]["fresh-adventure"]["available"])
        self.assertTrue(payload["results"]["another-adventure"]["available"])
        self.assertEqual(payload["selected"], "fresh-adventure")

    def test_check_suggested_names_none_available(self) -> None:
        payload, selected = check_suggested_names(["www", "admin", "play"])
        self.assertIsNone(selected)
        self.assertIn("All suggested names are busy", payload["message"])


class TestDomainGeneration(TestCase):
    def setUp(self) -> None:
        self.game = Game.objects.create(
            title="Таинственный замок",
            description="Увлекательное текстовое приключение в замке.",
            creation_time=now(),
        )
        self.model = LLMModel.objects.create(
            name="test/model",
            context_length=8000,
            input_cost=Decimal("1.0"),
            cached_input_cost=Decimal("0.0"),
            cache_write_cost=Decimal("0.0"),
            output_cost=Decimal("2.0"),
        )
        self.workflow, _ = LlmWorkflow.objects.update_or_create(
            name="playable_domain",
            defaults={
                "runner": "playable_domain",
                "prompt_template": (
                    "Pick a domain for {{ game.title }} on {{ base_domain }}."
                ),
                "model": self.model,
            },
        )

    @patch("curation.openrouter.chat_completion")
    def test_generate_playable_domain_success(
        self, mock_chat: MagicMock
    ) -> None:
        # First turn: suggest taken name; second turn: suggest free name
        Playable.objects.create(
            game=self.game,
            template="instead_em",
            template_version="1.0",
            slug="castle",
        )

        mock_chat.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "suggest_names",
                                        "arguments": '{"names": ["castle"]}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "function": {
                                        "name": "suggest_names",
                                        "arguments": (
                                            '{"names": ["mystic-castle"]}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 15},
            },
        ]

        slug = generate_playable_domain(self.game)
        self.assertEqual(slug, "mystic-castle")

        trajectory = LlmTrajectory.objects.filter(game=self.game).first()
        self.assertIsNotNone(trajectory)
        assert trajectory is not None
        self.assertEqual(trajectory.workflow, self.workflow)
        self.assertEqual(trajectory.model, self.model)
        self.assertGreater(len(trajectory.messages), 1)

    @patch(
        "curation.openrouter.chat_completion",
        side_effect=RuntimeError("API error"),
    )
    def test_generate_playable_domain_raises_on_error(
        self, mock_chat: MagicMock
    ) -> None:
        with self.assertRaises(RuntimeError):
            generate_playable_domain(self.game)

    @patch("curation.openrouter.chat_completion")
    def test_generate_playable_domain_raises_when_no_slug_selected(
        self, mock_chat: MagicMock
    ) -> None:
        mock_chat.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "No tool calls",
                    }
                }
            ],
            "usage": {},
        }
        with self.assertRaises(RuntimeError):
            generate_playable_domain(self.game)

    def test_generate_playable_domain_fails_when_workflow_missing(
        self,
    ) -> None:
        LlmWorkflow.objects.filter(name="playable_domain").delete()
        with self.assertRaises(LlmWorkflow.DoesNotExist):
            generate_playable_domain(self.game)
