from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils.timezone import now

from . import openrouter
from .edit import Approval, GameEditState, SourceFetchInfo, SourceStatus
from .gameinfo import GameInfo
from .llm import (
    LLM_RUNNERS,
    LlmWorkflowRunner,
    register_llm_runner,
    runner_for_workflow,
)
from .llm_runners.base import game_edit_state_context
from .models import (
    GameHistory,
    GameSource,
    GameSourceFetch,
    LLMModel,
    LlmTrajectory,
    LlmWorkflow,
)
from .passes.llm_workflow import LlmWorkflowPass


class CostForTests(TestCase):
    def test_cost_for_sums_four_rates_per_mtok(self):
        model = LLMModel(
            input_cost=Decimal("3"),
            cached_input_cost=Decimal("0.3"),
            cache_write_cost=Decimal("3.75"),
            output_cost=Decimal("15"),
        )
        # 1M each: 3 + 0.3 + 3.75 + 15 = 22.05
        self.assertEqual(
            model.cost_for(1_000_000, 1_000_000, 1_000_000, 1_000_000),
            Decimal("22.05"),
        )

    def test_cost_for_scales_with_token_counts(self):
        model = LLMModel(
            input_cost=Decimal("3"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("15"),
        )
        # 500k prompt -> 1.5, 200k completion -> 3.0
        self.assertEqual(
            model.cost_for(500_000, 0, 0, 200_000), Decimal("4.5")
        )

    def test_cost_for_zero_tokens_is_zero(self):
        model = LLMModel(
            input_cost=Decimal("3"),
            cached_input_cost=Decimal("0.3"),
            cache_write_cost=Decimal("3.75"),
            output_cost=Decimal("15"),
        )
        self.assertEqual(model.cost_for(0, 0, 0, 0), Decimal("0"))


class ModelFieldsTests(TestCase):
    def test_maps_pricing_to_dollars_per_mtok(self):
        entry = {
            "id": "anthropic/claude-opus",
            "context_length": 200_000,
            "pricing": {
                "prompt": "0.000003",
                "completion": "0.000015",
                "input_cache_read": "0.0000003",
                "input_cache_write": "0.00000375",
            },
        }
        self.assertEqual(
            openrouter.model_fields(entry),
            {
                "name": "anthropic/claude-opus",
                "context_length": 200_000,
                "input_cost": Decimal("3.000"),
                "output_cost": Decimal("15.000"),
                "cached_input_cost": Decimal("0.300"),
                "cache_write_cost": Decimal("3.750"),
            },
        )

    def test_missing_cache_pricing_defaults_to_zero(self):
        entry = {
            "id": "openai/gpt-mini",
            "context_length": 128_000,
            "pricing": {"prompt": "0.0000005", "completion": "0.0000015"},
        }
        fields = openrouter.model_fields(entry)
        self.assertEqual(fields["cached_input_cost"], Decimal("0"))
        self.assertEqual(fields["cache_write_cost"], Decimal("0"))
        self.assertEqual(fields["input_cost"], Decimal("0.5"))
        self.assertEqual(fields["output_cost"], Decimal("1.5"))


class TypicalCentsTests(TestCase):
    def test_uses_input_and_output_rates_in_cents(self):
        # input $3/Mtok, output $15/Mtok over the 11250/450 token profile.
        cents = openrouter.typical_cents(Decimal("3"), Decimal("15"))
        # (3 * 11250 + 15 * 450) / 1e6 = $0.0405 → 4.05¢
        self.assertEqual(cents, Decimal("4.05"))

    def test_variable_pricing_is_none(self):
        # OpenRouter auto-router models price as -1 ($/Mtok -1_000_000).
        self.assertIsNone(
            openrouter.typical_cents(Decimal("-1000000"), Decimal("-1000000"))
        )


def _entry(model_id, prompt, completion):
    return {
        "id": model_id,
        "context_length": 100_000,
        "pricing": {"prompt": prompt, "completion": completion},
    }


class UpdateAllViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="moder", email="moder@example.com"
        )
        self.user.groups.add(Group.objects.create(name="moder"))
        self.client.force_login(self.user)

    def _model(self, name, **kwargs):
        defaults = dict(
            context_length=100_000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("2"),
        )
        return LLMModel.objects.create(name=name, **{**defaults, **kwargs})

    def test_update_all_only_touches_changed_rows(self):
        # "stale" has a wrong input_cost; "fresh" already matches the catalog.
        stale = self._model("a/stale", input_cost=Decimal("9"))
        fresh = self._model("b/fresh", input_cost=Decimal("1"))
        catalog = [
            _entry("a/stale", "0.000001", "0.000002"),
            _entry("b/fresh", "0.000001", "0.000002"),
        ]

        with patch.object(openrouter, "fetch_models", return_value=catalog):
            response = self.client.post(
                "/curation/models/", {"action": "update_all"}
            )

        self.assertEqual(response.status_code, 302)
        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.input_cost, Decimal("1"))
        self.assertIsNotNone(stale.updated_at)
        self.assertIsNone(fresh.updated_at)


class LlmWorkflowRunnerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        @register_llm_runner
        class TestRunner(LlmWorkflowRunner):
            runner_name = "test_runner"

            def run(self):
                return self.run_agent_loop({"items": ["a", "b"]})

            def set_description(self, description: str) -> str:
                """Set the draft description."""
                self.state.current.description = description
                return "updated"

        cls.runner_cls = TestRunner

    @classmethod
    def tearDownClass(cls):
        LLM_RUNNERS.pop("test_runner", None)
        super().tearDownClass()

    def setUp(self):
        self.model = LLMModel.objects.create(
            name="openai/test",
            context_length=1000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0.1"),
            cache_write_cost=Decimal("2"),
            output_cost=Decimal("3"),
        )
        self.workflow = LlmWorkflow.objects.create(
            name="Test workflow",
            runner="test_runner",
            prompt_template="{% for item in items %}{{ item }}{% endfor %}",
            model=self.model,
            allowed_tools=["set_description"],
        )
        self.history = GameHistory.objects.create(creation_time=now())
        self.state = GameEditState(
            history=self.history,
            current=GameInfo(),
            approval=Approval.APPLIED,
            served=GameInfo(),
            last_applied=GameInfo(),
            sources=[],
        )

    def test_runner_for_workflow_uses_runner_field(self):
        runner = runner_for_workflow(self.workflow, self.state)

        self.assertIsInstance(runner, self.runner_cls)

    def test_agent_loop_runs_tool_and_records_trajectory(self):
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "set_description",
                                        "arguments": (
                                            '{"description": "New text"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "prompt_tokens_details": {
                        "cached_tokens": 3,
                        "cache_write_tokens": 4,
                    },
                },
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            trajectory = runner_for_workflow(self.workflow, self.state).run()

        self.assertEqual(self.state.current.description, "New text")
        self.assertEqual(chat.call_args_list[0].args[1][0]["content"], "ab")
        tool = chat.call_args_list[0].kwargs["tools"][0]
        self.assertEqual(tool["function"]["name"], "set_description")
        self.assertEqual(trajectory.prompt_tokens, 15)
        self.assertEqual(trajectory.cached_input_tokens, 3)
        self.assertEqual(trajectory.cache_write_tokens, 4)
        self.assertEqual(trajectory.completion_tokens, 3)
        self.assertEqual(trajectory.cost, Decimal("0.000032"))
        self.assertEqual(LlmTrajectory.objects.count(), 1)

    def test_pass_adapter_fetches_workflow_and_runs_registered_runner(self):
        self.state.current.description = "changed"
        with patch.object(openrouter, "chat_completion") as chat:
            chat.return_value = {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {},
            }

            LlmWorkflowPass().apply(
                self.state, {"workflow": self.workflow.name}
            )

        self.assertEqual(LlmTrajectory.objects.count(), 1)

    def test_pass_adapter_skips_when_already_proposed(self):
        self.state.approval = Approval.PROPOSED
        self.state.current.description = "changed"

        with patch.object(openrouter, "chat_completion") as chat:
            LlmWorkflowPass().apply(
                self.state, {"workflow": self.workflow.name}
            )

        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_pass_adapter_skips_when_no_diff(self):
        self.state.current = GameInfo(name="Same", description="Text")
        self.state.served = GameInfo(name="Same", description="Text")

        with patch.object(openrouter, "chat_completion") as chat:
            LlmWorkflowPass().apply(
                self.state, {"workflow": self.workflow.name}
            )

        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)


class HumanReviewRunnerTests(TestCase):
    def setUp(self):
        self.model = LLMModel.objects.create(
            name="google/gemma-test",
            context_length=1000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("1"),
        )
        self.workflow = LlmWorkflow.objects.create(
            name="human_review",
            runner="human_review",
            prompt_template=(
                "Approval: {{ approval }}\n"
                "Served:\n{{ served_canonical_text }}\n"
                "Current:\n{{ current_canonical_text }}"
            ),
            model=self.model,
            allowed_tools=["needs_human_review"],
        )
        self.history = GameHistory.objects.create(creation_time=now())
        self.source = GameSource.objects.create(
            history=self.history,
            type=GameSource.SourceType.IFWIKI,
            url="https://example.test/game",
        )
        self.fetch = GameSourceFetch.objects.create(
            source=self.source,
            raw_content="raw",
            canonical_text="canonical",
            canonical_text_hash="hash",
            first_fetch=now(),
            last_fetch=now(),
        )
        self.state = GameEditState(
            history=self.history,
            current=GameInfo(name="Title", description="Short"),
            approval=Approval.APPLIED,
            served=GameInfo(name="Title", description="Long text"),
            last_applied=GameInfo(name="Old", description="Old text"),
            sources=[
                SourceFetchInfo(
                    url=self.source.url,
                    type=self.source.type,
                    raw_content="raw",
                    canonical_text="canonical",
                    previous_raw_content="previous raw",
                    previous_canonical_text="previous canonical",
                    status=SourceStatus.CHANGED,
                    fetch=self.fetch,
                )
            ],
        )

    def test_context_contains_game_edit_state(self):
        context = game_edit_state_context(self.state)

        self.assertEqual(context["history"]["id"], self.history.id)
        self.assertEqual(context["approval"], "APPLIED")
        self.assertIn("Long text", context["served_canonical_text"])
        self.assertIn("Short", context["current_canonical_text"])
        self.assertIn("Old text", context["last_applied_canonical_text"])
        self.assertEqual(context["served"]["name"], "Title")
        self.assertEqual(context["current"]["description"], "Short")
        self.assertEqual(context["sources"][0]["status"], "CHANGED")
        self.assertEqual(context["sources"][0]["fetch_id"], self.fetch.id)
        self.assertEqual(
            context["sources"][0]["previous_canonical_text"],
            "previous canonical",
        )

    def test_runner_is_registered(self):
        runner = runner_for_workflow(self.workflow, self.state)

        self.assertEqual(runner.runner_name, "human_review")

    def test_tool_requests_human_review_and_records_trajectory(self):
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "needs_human_review",
                                        "arguments": (
                                            '{"reason": "Description lost"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            runner_for_workflow(self.workflow, self.state).run()

        prompt = chat.call_args_list[0].args[1][0]["content"]
        self.assertIn("Approval: APPLIED", prompt)
        self.assertIn("Long text", prompt)
        self.assertIn("Short", prompt)
        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertEqual(self.state.attention_reason, ["Description lost"])
        self.assertEqual(LlmTrajectory.objects.count(), 1)
