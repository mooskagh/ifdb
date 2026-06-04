from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated
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
from .llm_runners.content_editor import (
    ComplainParams,
    EditParams,
    FinishParams,
    MatchParams,
    PatchParams,
)
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

        @dataclass
        class SetDescriptionParams:
            description: Annotated[str, "New draft description"]
            note: str | None = None

        @register_llm_runner
        class TestRunner(LlmWorkflowRunner):
            runner_name = "test_runner"

            def __init__(
                self, workflow, state, *, include_tool=True, label="default"
            ):
                super().__init__(workflow, state)
                self.include_tool = include_tool
                self.label = label

            def run(self):
                return self.run_agent_loop({"items": ["a", "b"]})

            def tools(self):
                return (
                    {"set_description": self.set_description}
                    if self.include_tool
                    else {}
                )

            def set_description(self, params: SetDescriptionParams) -> dict:
                """Set the draft description."""
                self.state.current.description = params.description
                return {"status": "updated", "label": self.label}

        cls.runner_cls = TestRunner
        cls.set_description_params = SetDescriptionParams

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
            runner_params={"label": "configured"},
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
        self.assertEqual(runner.label, "configured")

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
        params = tool["function"]["parameters"]
        self.assertEqual(
            params["properties"]["description"]["description"],
            "New draft description",
        )
        self.assertIn("description", params["required"])
        self.assertNotIn("note", params["required"])
        self.assertEqual(
            trajectory.messages[2]["content"],
            '{"status": "updated", "label": "configured"}',
        )
        self.assertEqual(trajectory.prompt_tokens, 15)
        self.assertEqual(trajectory.cached_input_tokens, 3)
        self.assertEqual(trajectory.cache_write_tokens, 4)
        self.assertEqual(trajectory.completion_tokens, 3)
        self.assertEqual(trajectory.cost, Decimal("0.000032"))
        self.assertEqual(LlmTrajectory.objects.count(), 1)

    def test_runner_can_conditionally_disable_dynamic_tool(self):
        self.workflow.runner_params = {"include_tool": False}
        self.workflow.save(update_fields=["runner_params"])

        with patch.object(openrouter, "chat_completion") as chat:
            chat.return_value = {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {},
            }

            runner_for_workflow(self.workflow, self.state).run()

        self.assertEqual(chat.call_args.kwargs["tools"], [])

    def test_runner_can_stop_after_tool_call(self):
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
                                            '{"description": "Stop here"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {},
            },
        ]

        def should_stop(self, message, tool_results, step):
            return bool(tool_results)

        with (
            patch.object(self.runner_cls, "should_stop", should_stop),
            patch.object(
                openrouter, "chat_completion", side_effect=responses
            ) as chat,
        ):
            runner_for_workflow(self.workflow, self.state).run()

        self.assertEqual(chat.call_count, 1)
        self.assertEqual(self.state.current.description, "Stop here")

    def test_agent_loop_uses_configured_step_limit_over_old_default(self):
        self.workflow.runner_params = {"label": "configured"}
        self.workflow.save(update_fields=["runner_params"])
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{i}",
                                    "type": "function",
                                    "function": {
                                        "name": "set_description",
                                        "arguments": (
                                            f'{{"description": "Text {i}"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }
            for i in range(9)
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            runner_for_workflow(self.workflow, self.state).run_agent_loop(
                {}, max_steps=9
            )

        self.assertEqual(chat.call_count, 9)
        self.assertEqual(self.state.current.description, "Text 8")

    def test_agent_loop_renders_prompt_without_html_escaping(self):
        self.workflow.prompt_template = "{{ description }}"
        self.workflow.save(update_fields=["prompt_template"])
        self.state.current.description = 'Text with "quotes" & ampersand'

        with patch.object(openrouter, "chat_completion") as chat:
            chat.return_value = {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {},
            }
            runner_for_workflow(self.workflow, self.state).run_agent_loop({
                "description": 'Text with "quotes" & ampersand'
            })

        self.assertEqual(
            chat.call_args.args[1][0]["content"],
            'Text with "quotes" & ampersand',
        )

    def test_agent_loop_stops_after_error_tool_limit(self):
        self.workflow.runner_params = {"label": "configured"}
        self.workflow.save(update_fields=["runner_params"])
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{i}",
                                    "type": "function",
                                    "function": {
                                        "name": "set_description",
                                        "arguments": (
                                            '{"description": "error"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }
            for i in range(3)
        ]

        with (
            patch.object(
                self.runner_cls,
                "_run_tool_call",
                return_value={
                    "role": "tool",
                    "tool_call_id": "call",
                    "name": "set_description",
                    "content": '{"status": "error", "error": "bad"}',
                },
            ),
            patch.object(
                openrouter, "chat_completion", side_effect=responses
            ) as chat,
        ):
            runner = runner_for_workflow(self.workflow, self.state)
            trajectory = runner.run_agent_loop({}, max_error_tool_calls=2)

        self.assertEqual(chat.call_count, 2)
        self.assertEqual(runner.stop_reason, "max_error_tool_calls")
        self.assertEqual(len(trajectory.messages), 5)

    def test_game_edit_runner_marks_attention_when_error_limit_hit(self):
        self.workflow.runner = "content_editor"
        self.workflow.runner_params = {"max_error_tool_calls": 2}
        self.workflow.save(update_fields=["runner", "runner_params"])
        self.state.current.description = "Body"
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{i}",
                                    "type": "function",
                                    "function": {
                                        "name": "edit",
                                        "arguments": (
                                            '{"rationale":"test",'
                                            '"match":{"text_start":"missing",'
                                            '"text_end":"missing"},'
                                            '"edit":{"replace":"New"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            }
            for i in range(2)
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ):
            trajectory = runner_for_workflow(self.workflow, self.state).run()

        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertEqual(
            self.state.attention_reason,
            [
                'LLM workflow "Test workflow" stopped after too many '
                f"failed tool calls; review trajectory #{trajectory.pk}."
            ],
        )

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

    def test_pass_adapter_marks_attention_when_workflow_fails(self):
        self.state.current.description = "changed"

        with patch.object(openrouter, "chat_completion") as chat:
            chat.side_effect = RuntimeError("network down")
            LlmWorkflowPass().apply(
                self.state, {"workflow": self.workflow.name}
            )

        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertEqual(
            self.state.attention_reason,
            [
                'LLM workflow "Test workflow" failed: network down; '
                "review logs."
            ],
        )

    def test_pass_adapter_runs_when_already_proposed(self):
        self.state.approval = Approval.PROPOSED
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

        chat.assert_called_once()
        self.assertEqual(LlmTrajectory.objects.count(), 1)

    def test_pass_adapter_skips_when_rejected(self):
        self.state.approval = Approval.REJECTED
        self.state.current.description = "changed"

        with patch.object(openrouter, "chat_completion") as chat:
            LlmWorkflowPass().apply(
                self.state, {"workflow": self.workflow.name}
            )

        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_pass_adapter_skips_when_cancelled(self):
        self.state.approval = Approval.CANCELLED
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
        self.assertEqual(context["served_content_text"], "Long text")
        self.assertEqual(context["current_content_text"], "Short")
        self.assertEqual(context["last_applied_content_text"], "Old text")
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
        self.assertEqual(chat.call_count, 1)


class ContentEditorRunnerTests(TestCase):
    def setUp(self):
        self.model = LLMModel.objects.create(
            name="openai/editor-test",
            context_length=1000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("1"),
        )
        self.workflow = LlmWorkflow.objects.create(
            name="content_editor",
            runner="content_editor",
            prompt_template="Current:\n{{ current_content_text }}",
            model=self.model,
        )
        self.history = GameHistory.objects.create(creation_time=now())
        self.state = GameEditState(
            history=self.history,
            current=GameInfo(
                name="Title",
                description="First line\nSecond line\nThird line",
            ),
            approval=Approval.APPLIED,
            served=GameInfo(name="Title", description="First line"),
            last_applied=GameInfo(),
            sources=[],
        )

    def _runner(self):
        return runner_for_workflow(self.workflow, self.state)

    def test_runner_is_registered_and_resolution_schema_is_enum(self):
        runner = self._runner()

        names = {tool["function"]["name"] for tool in runner._tools_schema()}
        self.assertEqual(names, {"complain", "edit", "finish"})
        edit = next(
            tool
            for tool in runner._tools_schema()
            if tool["function"]["name"] == "edit"
        )
        finish = next(
            tool
            for tool in runner._tools_schema()
            if tool["function"]["name"] == "finish"
        )

        edit_params = edit["function"]["parameters"]["properties"]
        self.assertIn("replace", edit_params["edit"]["required"])
        self.assertNotIn("insert_before", edit_params["edit"]["properties"])
        self.assertNotIn("insert_after", edit_params["edit"]["properties"])
        resolution = finish["function"]["parameters"]["properties"][
            "resolution"
        ]
        self.assertEqual(resolution["type"], "string")
        self.assertEqual(
            resolution["enum"],
            ["abort", "commit", "request_human_review"],
        )

    def test_complain_records_feedback_without_mutating_state(self):
        result = self._runner().complain(
            ComplainParams(
                complaint="Need structured URL editing",
                suggestion="Add add_url/remove_url tools",
            )
        )

        self.assertEqual(result, {"status": "complaint_recorded"})
        self.assertEqual(
            self.state.current.description,
            "First line\nSecond line\nThird line",
        )

    def test_edit_replaces_text_and_returns_post_edit_line_snippet(self):
        result = self._runner().edit(
            self._edit_params(
                "Second line",
                "Second line",
                replace="Changed line",
            )
        )

        self.assertEqual(result["status"], "edited")
        self.assertEqual(
            self.state.current.description,
            "First line\nChanged line\nThird line",
        )
        self.assertIn("First line", result["snippet"])
        self.assertIn("Changed line", result["snippet"])
        self.assertIn("Third line", result["snippet"])

    def test_edit_only_changes_description_body(self):
        result = self._runner().edit(
            self._edit_params("Title", "Title", replace="Changed")
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(self.state.current.name, "Title")
        self.assertEqual(
            self.state.current.description,
            "First line\nSecond line\nThird line",
        )

    def test_tool_call_coerces_nested_edit_params(self):
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
                                        "name": "edit",
                                        "arguments": (
                                            '{"rationale":"test",'
                                            '"match":{'
                                            '"text_start":"Second line",'
                                            '"text_end":"Second line"},'
                                            '"edit":{'
                                            '"replace":"Changed line"}}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}}
                ],
                "usage": {},
            },
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ):
            self._runner().run()

        self.assertEqual(
            self.state.current.description,
            "First line\nChanged line\nThird line",
        )

    def test_edit_requires_occurrence_only_for_duplicate_text_start(self):
        self.state.current.description = "same one\nsame two"

        duplicate = self._runner().edit(
            self._edit_params("same", "one", replace="first")
        )
        unique = self._runner().edit(
            self._edit_params(
                "same two",
                "same two",
                occurrence=1,
                replace="second",
            )
        )

        self.assertEqual(duplicate["status"], "error")
        self.assertIn("found 2 times", duplicate["error"])
        self.assertEqual(unique["status"], "error")
        self.assertIn("unique", unique["error"])

    def test_edit_uses_occurrence_and_can_delete(self):
        self.state.current.description = "same one\nsame two"
        runner = self._runner()

        replaced = runner.edit(
            self._edit_params(
                "same",
                "two",
                occurrence=2,
                replace="before same two after",
            )
        )
        deleted = runner.edit(
            self._edit_params("same one\n", "same one\n", replace="")
        )

        self.assertEqual(replaced["status"], "edited")
        self.assertEqual(deleted["status"], "edited")
        self.assertEqual(
            self.state.current.description, "before same two after"
        )

    def test_edit_error_does_not_mutate_state(self):
        result = self._runner().edit(
            self._edit_params("missing", "missing", replace="New")
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(
            self.state.current.description,
            "First line\nSecond line\nThird line",
        )

    def test_finish_abort_restores_original_and_cancels(self):
        runner = self._runner()
        runner.edit(
            self._edit_params("Second line", "Second line", replace="Changed")
        )

        result = runner.finish(
            FinishParams(summary="Bad edit", resolution="abort")
        )

        self.assertEqual(result["status"], "finished")
        self.assertEqual(self.state.approval, Approval.CANCELLED)
        self.assertEqual(
            self.state.current.description,
            "First line\nSecond line\nThird line",
        )

    def test_finish_human_review_marks_proposed(self):
        result = self._runner().finish(
            FinishParams(
                summary="Needs review", resolution="request_human_review"
            )
        )

        self.assertEqual(result["resolution"], "request_human_review")
        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertEqual(self.state.attention_reason, ["Needs review"])

    def _edit_params(
        self,
        text_start,
        text_end,
        *,
        replace,
        occurrence=None,
    ):
        return EditParams(
            rationale="test",
            match=MatchParams(text_start, text_end, occurrence),
            edit=PatchParams(replace),
        )
