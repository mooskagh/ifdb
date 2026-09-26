import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.timezone import now

from curation import openrouter
from curation.edit import (
    Approval,
    GameEditState,
    SourceFetchInfo,
    SourceStatus,
)
from curation.llm import (
    LLM_RUNNERS,
    LlmWorkflowRunner,
    register_llm_runner,
    runner_for_workflow,
)
from curation.llm_runners.base import game_edit_state_context
from curation.llm_runners.content_editor import (
    ComplainParams,
    FinishParams,
    InsertLinesParams,
    ReplaceLinesParams,
    ReplaceTextParams,
    SourceRef,
    UndoParams,
)
from curation.llm_runners.status_review import SetStatusParams
from curation.models import (
    EditPipeline,
    GameCuration,
    GameSource,
    GameSourceFetch,
    LLMModel,
    LlmTrajectory,
    LlmWorkflow,
)
from curation.passes.llm_workflow import LlmWorkflowPass
from curation.passes.merge_sources import build_description_delta
from games.gameinfo import GameInfo
from games.models import Game


class ChatCompletionTests(TestCase):
    def test_includes_tool_choice_when_requested(self):
        with patch.object(openrouter.requests, "post") as post:
            post.return_value.json.return_value = {"ok": True}

            result = openrouter.chat_completion(
                "model",
                [{"role": "user", "content": "Prompt"}],
                tools=[{"type": "function"}],
                tool_choice="required",
            )

        self.assertEqual(result, {"ok": True})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["tool_choice"], "required")

    def test_openrouter_error_payload_is_logged_and_raised(self):
        with patch.object(openrouter.requests, "post") as post:
            post.return_value.json.return_value = {
                "error": {"message": "tools are not supported"}
            }

            with (
                self.assertLogs("worker", level="ERROR") as logs,
                self.assertRaisesRegex(ValueError, "OpenRouter error"),
            ):
                openrouter.chat_completion("model", [])

        self.assertIn("tools are not supported", logs.output[0])


def _entry(model_id, prompt, completion):
    return {
        "id": model_id,
        "context_length": 100_000,
        "pricing": {"prompt": prompt, "completion": completion},
    }


class UpdateAllViewTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            username="admin", email="admin@example.com", is_superuser=True
        )
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
        game = Game.objects.create(
            state=Game.State.DRAFT, title="LLM Game", creation_time=now()
        )
        self.history = GameCuration.objects.create(game=game)
        self.state = GameEditState(
            curation=self.history,
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

    def test_agent_loop_skips_later_batched_calls_after_error(self):
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
                                            '{"description": "error"}'
                                        ),
                                    },
                                },
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "set_description",
                                        "arguments": (
                                            '{"description": "Should not run"}'
                                        ),
                                    },
                                },
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
        executed_calls = []

        def run_tool_call(runner, call, tool_methods):
            self.assertEqual(call["id"], "call_1")
            executed_calls.append(call["id"])
            return {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": "set_description",
                "content": '{"status": "error", "error": "bad edit"}',
            }

        with (
            patch.object(self.runner_cls, "_run_tool_call", run_tool_call),
            patch.object(openrouter, "chat_completion", side_effect=responses),
        ):
            trajectory = runner_for_workflow(
                self.workflow, self.state
            ).run_agent_loop({})

        self.assertEqual(executed_calls, ["call_1"])
        self.assertEqual(trajectory.messages[3]["tool_call_id"], "call_2")
        skipped = json.loads(trajectory.messages[3]["content"])
        self.assertEqual(skipped["status"], "error")
        self.assertIn("not executed", skipped["error"])
        self.assertIn("earlier tool call", skipped["error"])

    def test_required_tool_loop_retries_missing_tool_calls(self):
        responses = [
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "text"}}
                ],
                "usage": {},
            },
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
                                            '{"description": "Used tool"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
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
            runner_for_workflow(self.workflow, self.state).run_agent_loop(
                {}, require_tool=True
            )

        self.assertEqual(chat.call_count, 2)
        self.assertEqual(
            chat.call_args_list[0].kwargs["tool_choice"], "required"
        )
        self.assertEqual(self.state.current.description, "Used tool")

    def test_required_tool_loop_stops_after_missing_tool_limit(self):
        responses = [
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "text"}}
                ],
                "usage": {},
            }
            for _ in range(2)
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            runner = runner_for_workflow(self.workflow, self.state)
            trajectory = runner.run_agent_loop(
                {}, require_tool=True, max_error_tool_calls=2
            )

        self.assertEqual(chat.call_count, 2)
        self.assertEqual(runner.stop_reason, "missing_tool_calls")
        self.assertEqual(len(trajectory.messages), 3)

    def test_agent_loop_logs_response_without_choices(self):
        with patch.object(
            openrouter,
            "chat_completion",
            return_value={"error": {"message": "bad request"}},
        ):
            with (
                self.assertLogs("worker", level="ERROR") as logs,
                self.assertRaisesRegex(ValueError, "missing choices"),
            ):
                runner_for_workflow(
                    self.workflow, self.state
                ).run_agent_loop({})

        self.assertIn("has no choices", logs.output[0])
        self.assertIn("bad request", logs.output[0])

    def test_game_edit_runner_marks_attention_when_error_limit_hit(self):
        self.workflow.runner = "content_editor"
        self.workflow.runner_params = {"max_error_tool_calls": 2}
        self.workflow.save(update_fields=["runner", "runner_params"])
        self.state.current.description = "Body"
        self.state.served.description = "Previous body"
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
                                        "name": "replace_text",
                                        "arguments": (
                                            '{"rationale":"test",'
                                            '"start_line":1,"end_line":1,'
                                            '"old":"missing","new":"New"}'
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

        self.assertEqual(self.state.approval, Approval.REJECTED)
        self.assertIs(self.state.needs_attention, True)
        self.assertEqual(
            self.state.notes,
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
            with self.assertLogs("worker", level="ERROR") as logs:
                LlmWorkflowPass().apply(
                    self.state, {"workflow": self.workflow.name}
                )

        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertIs(self.state.needs_attention, True)
        self.assertIn("LLM workflow 'Test workflow' failed", logs.output[0])
        self.assertIn("network down", logs.output[0])
        self.assertEqual(
            self.state.notes,
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

    def test_pass_adapter_skips_when_only_final_newline_differs(self):
        self.state.current = GameInfo(name="Same", description="Text\n")
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
        game = Game.objects.create(
            state=Game.State.DRAFT, title="LLM Game", creation_time=now()
        )
        self.history = GameCuration.objects.create(game=game)
        self.source = GameSource.objects.create(
            game=game,
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
            curation=self.history,
            current=GameInfo(
                name="Title", date="2025-01-02", description="Short"
            ),
            approval=Approval.APPLIED,
            served=GameInfo(
                name="Title", date="2024-01-02", description="Long text"
            ),
            last_applied=GameInfo(
                name="Old", date="2023-01-02", description="Old text"
            ),
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
        self.assertIn("note", context["history"])
        self.assertNotIn("attention_reason", context["history"])
        self.assertEqual(context["approval"], "APPLIED")
        self.assertEqual(context["notes"], [])
        self.assertIs(context["needs_attention"], False)
        self.assertNotIn("attention_reason", context)
        self.assertIn("Long text", context["served_canonical_text"])
        self.assertIn("Short", context["current_canonical_text"])
        self.assertIn("Old text", context["last_applied_canonical_text"])
        self.assertEqual(
            context["served_metadata_yaml"],
            '- name: "Title"\n- release_date: "2024-01-02"',
        )
        self.assertEqual(
            context["current_metadata_yaml"],
            '- name: "Title"\n- release_date: "2025-01-02"',
        )
        self.assertEqual(
            context["last_applied_metadata_yaml"],
            '- name: "Old"\n- release_date: "2023-01-02"',
        )
        self.assertNotIn("Long text", context["served_metadata_yaml"])
        self.assertNotIn("Short", context["current_metadata_yaml"])
        self.assertEqual(context["served_content_text"], "Long text")
        self.assertEqual(context["current_content_text"], "Short")
        self.assertEqual(context["last_applied_content_text"], "Old text")
        self.assertIn("--- served", context["metadata_yaml_diff"])
        self.assertIn("+++ edited", context["metadata_yaml_diff"])
        self.assertIn(
            '-- release_date: "2024-01-02"', context["metadata_yaml_diff"]
        )
        self.assertIn(
            '+- release_date: "2025-01-02"', context["metadata_yaml_diff"]
        )
        self.assertIn("--- served", context["content_text_diff"])
        self.assertIn("+++ edited", context["content_text_diff"])
        self.assertIn("-Long text", context["content_text_diff"])
        self.assertIn("+Short", context["content_text_diff"])
        self.assertIn("--- served", context["canonical_text_diff"])
        self.assertIn("+++ edited", context["canonical_text_diff"])
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
        self.assertIs(self.state.needs_attention, True)
        self.assertEqual(self.state.notes, ["Description lost"])
        self.assertEqual(LlmTrajectory.objects.count(), 1)
        self.assertEqual(chat.call_count, 1)


class StatusReviewRunnerTests(TestCase):
    def setUp(self):
        self.model = LLMModel.objects.create(
            name="openai/status-test",
            context_length=1000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("1"),
        )
        self.workflow = LlmWorkflow.objects.create(
            name="status_review",
            runner="status_review",
            prompt_template="Diff:\n{{ content_text_diff }}",
            model=self.model,
        )
        game = Game.objects.create(
            state=Game.State.DRAFT, title="LLM Game", creation_time=now()
        )
        self.history = GameCuration.objects.create(game=game)
        self.state = GameEditState(
            curation=self.history,
            current=GameInfo(name="Title", description="New"),
            approval=Approval.PROPOSED,
            served=GameInfo(name="Title", description="Old"),
            last_applied=GameInfo(),
            sources=[],
        )

    def _runner(self):
        return runner_for_workflow(self.workflow, self.state)

    def test_runner_is_registered_and_schema_uses_status_enum(self):
        runner = self._runner()

        tools = runner._tools_schema()
        self.assertEqual(
            [tool["function"]["name"] for tool in tools], ["set_status"]
        )
        status = tools[0]["function"]["parameters"]["properties"]["status"]
        self.assertEqual(status["enum"], ["accept", "needs_human_review"])

    def test_run_skips_when_status_is_not_applied(self):
        for approval in [
            Approval.PROPOSED,
            Approval.REJECTED,
            Approval.CANCELLED,
        ]:
            with self.subTest(approval=approval):
                self.state.approval = approval
                with patch.object(openrouter, "chat_completion") as chat:
                    trajectory = self._runner().run()

                self.assertIsNone(trajectory)
                chat.assert_not_called()
                self.assertEqual(self.state.approval, approval)
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_run_skips_when_served_is_empty(self):
        self.state.approval = Approval.APPLIED
        self.state.served = GameInfo()

        with patch.object(openrouter, "chat_completion") as chat:
            trajectory = self._runner().run()

        self.assertIsNone(trajectory)
        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_run_skips_when_served_description_is_blank(self):
        self.state.approval = Approval.APPLIED
        self.state.served.description = " \n\t "

        with patch.object(openrouter, "chat_completion") as chat:
            trajectory = self._runner().run()

        self.assertIsNone(trajectory)
        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_run_skips_when_content_matches_served(self):
        self.state.approval = Approval.APPLIED
        self.state.current = GameInfo(name="Different", description="Old")

        with patch.object(openrouter, "chat_completion") as chat:
            trajectory = self._runner().run()

        self.assertIsNone(trajectory)
        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)

    def test_set_status_accept_marks_applied_and_clears_attention(self):
        self.state.needs_attention = True

        result = self._runner().set_status(
            SetStatusParams(rationale="The diff is safe", status="accept")
        )

        self.assertEqual(result, {"status": "set", "approval": "APPLIED"})
        self.assertEqual(self.state.approval, Approval.APPLIED)
        self.assertIs(self.state.needs_attention, False)
        self.assertEqual(self.state.notes, [])

    def test_set_status_needs_human_review_marks_attention_and_notes(self):
        result = self._runner().set_status(
            SetStatusParams(
                rationale="Source conflict",
                status="needs_human_review",
            )
        )

        self.assertEqual(result, {"status": "set", "approval": "PROPOSED"})
        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertIs(self.state.needs_attention, True)
        self.assertEqual(self.state.notes, ["Review needed: Source conflict"])

    def test_run_requires_tool_call_and_records_trajectory(self):
        self.state.approval = Approval.APPLIED
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
                                        "name": "set_status",
                                        "arguments": (
                                            '{"rationale":"Safe",'
                                            '"status":"accept"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            }
        ]

        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            trajectory = self._runner().run()

        prompt = chat.call_args.args[1][0]["content"]
        self.assertIn("--- served", prompt)
        self.assertIn("+++ edited", prompt)
        self.assertIn("-Old", prompt)
        self.assertIn("+New", prompt)
        self.assertEqual(chat.call_args.kwargs["tool_choice"], "required")
        self.assertEqual(self.state.approval, Approval.APPLIED)
        self.assertEqual(LlmTrajectory.objects.get(), trajectory)


class ContentEditorRunnerTests(TestCase):
    def setUp(self):
        self.model = LLMModel.objects.create(
            name="editor-test",
            context_length=1000,
            input_cost=Decimal("1"),
            cached_input_cost=Decimal("0"),
            cache_write_cost=Decimal("0"),
            output_cost=Decimal("1"),
        )
        self.workflow = LlmWorkflow.objects.create(
            name="content_editor",
            runner="content_editor",
            prompt_template="{{ numbered_files }}",
            model=self.model,
        )
        game = Game.objects.create(
            state=Game.State.DRAFT, title="LLM Game", creation_time=now()
        )
        self.state = GameEditState(
            curation=GameCuration.objects.create(game=game),
            current=GameInfo(name="Title", description="First\nSecond\nThird"),
            served=GameInfo(name="Title", description="First"),
            last_applied=GameInfo(),
            approval=Approval.APPLIED,
            sources=[],
        )

    def runner(self):
        return runner_for_workflow(self.workflow, self.state)

    def test_schema_and_exclusive_content(self):
        runner = self.runner()
        tools = {
            t["function"]["name"]: t["function"]
            for t in runner._tools_schema()
        }
        self.assertEqual(
            set(tools),
            {
                "replace_lines",
                "insert_lines",
                "replace_text",
                "undo",
                "finish",
                "complain",
            },
        )
        self.assertEqual(
            set(
                tools["replace_lines"]["parameters"]["properties"]["source"][
                    "properties"
                ]
            ),
            {"file", "start_line", "end_line"},
        )
        self.assertEqual(
            tools["finish"]["parameters"]["properties"]["resolution"]["enum"],
            ["commit", "abort", "request_human_review"],
        )
        for text, source in ((None, None), ("x", SourceRef("notes", 1, 1))):
            result = runner.replace_lines(
                ReplaceLinesParams(2, 2, "test", text, source)
            )
            self.assertEqual(result["status"], "error")
            self.assertIn("exactly one", result["error"])
        self.assertEqual(
            self.state.current.description, "First\nSecond\nThird"
        )

        self.assertEqual(
            runner.replace_lines(
                ReplaceLinesParams(2, 2, "delete", "", SourceRef("", 0, 0))
            )["current_text"],
            "First\nThird",
        )
        self.assertEqual(
            runner.insert_lines(
                InsertLinesParams(
                    1, "after", "insert", "New", SourceRef("", 0, 0)
                )
            )["current_text"],
            "First\nNew\nThird",
        )
        self.assertEqual(
            runner.replace_lines(
                ReplaceLinesParams(2, 2, "invalid", "x", SourceRef("", 1, 1))
            )["status"],
            "error",
        )
        self.assertEqual(self.state.current.description, "First\nNew\nThird")

    def test_readonly_copy_numbering_and_undo(self):
        self.workflow.runner_params = {
            "readonly_files": [{"name": "notes", "text": "A\r\nB\r\n"}]
        }
        runner = self.runner()
        self.assertIn(
            "FILE: notes [readonly]\n1: A\n2: B",
            runner.context()["numbered_files"],
        )
        self.assertIn(
            "FILE: current [editable]\n1: First",
            runner.context()["numbered_files"],
        )
        self.assertIn(
            "FILE: current [editable]\n1: First",
            runner.context()["current_file"],
        )
        first = runner.replace_lines(
            ReplaceLinesParams(2, 2, "copy", source=SourceRef("notes", 1, 2))
        )
        self.assertEqual(first["current_text"], "First\nA\r\nB\r\nThird")
        self.assertIn("4: Third", first["current_file"])
        second = runner.insert_lines(
            InsertLinesParams(3, "after", "insert", text="Extra")
        )
        self.assertIn("4: Extra\n5: Third", second["current_file"])
        self.assertEqual(
            runner.undo(UndoParams("undo"))["current_file"],
            first["current_file"],
        )

    def test_bad_ranges_sources_and_ambiguity_leave_text_untouched(self):
        self.workflow.runner_params = {
            "readonly_files": [{"name": "notes", "text": "A\n"}]
        }
        runner = self.runner()
        old = self.state.current.description
        for operation in (
            lambda: runner.replace_lines(
                ReplaceLinesParams(0, 1, "bad", text="X")
            ),
            lambda: runner.replace_lines(
                ReplaceLinesParams(2, 4, "bad", text="X")
            ),
            lambda: runner.insert_lines(
                InsertLinesParams(4, "after", "bad", text="X")
            ),
            lambda: runner.replace_lines(
                ReplaceLinesParams(
                    2, 2, "bad", source=SourceRef("current", 1, 1)
                )
            ),
            lambda: runner.replace_lines(
                ReplaceLinesParams(
                    2, 2, "bad", source=SourceRef("notes", 1, 2)
                )
            ),
            lambda: runner.replace_text(
                ReplaceTextParams(1, 3, "", "X", "bad")
            ),
        ):
            result = operation()
            self.assertEqual(result["status"], "error")
            self.assertIn("FILE: current [editable]", result["current_file"])
            self.assertEqual(self.state.current.description, old)
        self.state.current.description = "repeat\nrepeat\nunique"
        runner = self.runner()
        for start, end in ((1, 2), (3, 3)):
            self.assertEqual(
                runner.replace_text(
                    ReplaceTextParams(start, end, "repeat", "new", "test")
                )["status"],
                "error",
            )
        self.assertEqual(
            self.state.current.description, "repeat\nrepeat\nunique"
        )
        self.assertEqual(
            runner.replace_text(
                ReplaceTextParams(2, 2, "repeat", "new", "test")
            )["current_text"],
            "repeat\nnew\nunique",
        )
        for name in ("notes", "current", ""):
            self.workflow.runner_params = {
                "readonly_files": [
                    {"name": "notes", "text": "a"},
                    {"name": name, "text": "b"},
                ]
            }
            with self.assertRaises(ValueError):
                self.runner()

    def test_blank_lines_crlf_terminal_newline_and_empty_file(self):
        self.state.current.description = "A\r\n\r\nC\r\n"
        runner = self.runner()
        self.assertIn("1: A\n2: \n3: C", runner.context()["numbered_files"])
        self.assertEqual(
            runner.replace_lines(ReplaceLinesParams(2, 2, "edit", text="B"))[
                "current_text"
            ],
            "A\r\nB\r\nC\r\n",
        )
        self.assertEqual(
            runner.replace_lines(ReplaceLinesParams(1, 3, "delete", text=""))[
                "current_text"
            ],
            "",
        )
        self.assertEqual(
            runner.insert_lines(
                InsertLinesParams(1, "before", "start", text="New")
            )["current_text"],
            "New",
        )
        self.assertEqual(
            runner.insert_lines(
                InsertLinesParams(1, "after", "append", text="Last")
            )["current_text"],
            "New\nLast",
        )

    def test_finish_attention_and_complaint(self):
        self.assertEqual(
            self.runner().finish(FinishParams("commit", "No duplicates"))[
                "resolution"
            ],
            "commit",
        )
        runner = self.runner()
        runner.replace_lines(ReplaceLinesParams(0, 1, "bad", text="X"))
        self.assertEqual(
            runner.finish(FinishParams("commit", "Done"))["resolution"],
            "request_human_review",
        )
        self.assertEqual(self.state.approval, Approval.PROPOSED)
        self.assertTrue(self.state.needs_attention)
        runner = self.runner()
        runner.replace_lines(ReplaceLinesParams(2, 2, "edit", text="Changed"))
        self.assertEqual(
            runner.finish(FinishParams("commit", "Done"))["resolution"],
            "commit",
        )
        runner = self.runner()
        runner.replace_lines(ReplaceLinesParams(2, 2, "edit", text="Other"))
        self.assertEqual(
            runner.finish(FinishParams("abort", "Undo"))["resolution"], "abort"
        )
        self.assertEqual(
            self.state.current.description, "First\nChanged\nThird"
        )
        self.assertEqual(self.state.approval, Approval.REJECTED)
        self.assertEqual(
            self.runner().finish(
                FinishParams("request_human_review", "Unsure")
            )["resolution"],
            "request_human_review",
        )
        self.assertEqual(
            self.runner().complain(ComplainParams("Need URL tool"))["status"],
            "complaint_recorded",
        )

    def test_mocked_prompt_and_tool_trajectory(self):
        self.workflow.runner_params = {
            "readonly_files": [{"name": "notes", "text": "Source\n"}]
        }
        responses = []
        for index, (name, args) in enumerate(
            (
                (
                    "replace_lines",
                    {
                        "start_line": 2,
                        "end_line": 2,
                        "text": "Changed",
                        "rationale": "edit",
                    },
                ),
                ("finish", {"resolution": "commit", "summary": "Done"}),
            ),
            1,
        ):
            responses.append({
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{index}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            })
        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            self.assertIsNotNone(self.runner().run())
        self.assertIn(
            "FILE: current [editable]\n1: First",
            chat.call_args_list[0].args[1][0]["content"],
        )
        self.assertIn(
            "FILE: notes [readonly]\n1: Source",
            chat.call_args_list[0].args[1][0]["content"],
        )
        self.assertIn(
            "2: Changed", chat.call_args_list[1].args[1][2]["content"]
        )
        self.assertEqual(
            self.state.current.description, "First\nChanged\nThird"
        )

    def test_incomplete_run_marks_attention(self):
        self.workflow.runner_params = {"max_error_tool_calls": 2}
        self.workflow.save(update_fields=["runner_params"])
        response = {
            "choices": [{"message": {"role": "assistant", "content": "done"}}],
            "usage": {},
        }
        with patch.object(
            openrouter, "chat_completion", side_effect=[response, response]
        ) as chat:
            self.assertIsNotNone(self.runner().run())
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(
            chat.call_args_list[0].kwargs["tool_choice"], "required"
        )
        self.assertEqual(self.state.approval, Approval.REJECTED)
        self.assertTrue(self.state.needs_attention)

    def test_skips_empty_and_fresh_single_source(self):
        self.state.current.description = " \n "
        with patch.object(openrouter, "chat_completion") as chat:
            self.assertIsNone(self.runner().run())
        chat.assert_not_called()
        self.state.current.description = "Some text"
        self.state.served.description = None
        with patch.object(openrouter, "chat_completion") as chat:
            self.assertIsNone(self.runner().run())
        chat.assert_not_called()
        self.assertEqual(LlmTrajectory.objects.count(), 0)


class UpdateDescriptionTests(TestCase):
    def setUp(self):
        model = LLMModel.objects.create(
            name="update-description-test",
            context_length=1000,
            input_cost=1,
            cached_input_cost=0,
            cache_write_cost=0,
            output_cost=1,
        )
        self.workflow = LlmWorkflow.objects.create(
            name="update-description-test",
            runner="update_description",
            prompt_template="{{ numbered_files }}",
            model=model,
        )
        game = Game.objects.create(
            state=Game.State.DRAFT, title="LLM Game", creation_time=now()
        )
        self.state = GameEditState(
            curation=GameCuration.objects.create(game=game),
            current=GameInfo(name="Title", description="Old\nHuman note"),
            served=GameInfo(name="Title"),
            last_applied=GameInfo(),
            approval=Approval.APPLIED,
            sources=[],
        )

    def source(
        self, kind, old=None, new=None, *, old_name="Title", new_name="Title"
    ):
        source = GameSource.objects.create(
            game=self.state.curation.game,
            type=kind,
            url=f"https://example.test/{GameSource.objects.count()}",
        )

        def fetch(description, name):
            if description is None:
                return None
            text = GameInfo(name=name, description=description).to_canonical()
            return GameSourceFetch.objects.create(
                source=source,
                raw_content="",
                canonical_text=text,
                canonical_text_hash=str(GameSourceFetch.objects.count()),
                first_fetch=now(),
                last_fetch=now(),
            )

        previous, current = fetch(old, old_name), fetch(new, new_name)
        return SourceFetchInfo(
            url=source.url,
            type=source.type,
            raw_content="" if current else None,
            canonical_text=current.canonical_text if current else None,
            previous_raw_content="" if previous else None,
            previous_canonical_text=previous.canonical_text
            if previous
            else None,
            status=SourceStatus.CHANGED,
            fetch=current,
            previous_fetch=previous,
        )

    def test_delta_orders_changed_new_disappeared_and_ignores_metadata(self):
        new = self.source(GameSource.SourceType.IFWIKI, new="New wiki")
        first = self.source(GameSource.SourceType.AXMA, "Old A", "New A")
        second = self.source(GameSource.SourceType.AXMA, "Old B", "New B")
        gone = self.source(GameSource.SourceType.QSP, old="Gone")
        metadata = self.source(
            GameSource.SourceType.STICKY_NOTE,
            "Same",
            "Same",
            old_name="Before",
            new_name="After",
        )
        delta = build_description_delta([gone, second, metadata, first, new])

        self.assertEqual(
            delta.pairs,
            [
                (None, new.fetch),
                (second.previous_fetch, second.fetch),
                (first.previous_fetch, first.fetch),
                (gone.previous_fetch, None),
            ],
        )
        self.assertEqual(
            delta.old_ids,
            [
                second.previous_fetch.pk,
                first.previous_fetch.pk,
                gone.previous_fetch.pk,
            ],
        )
        self.assertEqual(
            delta.new_ids,
            [
                new.fetch.pk,
                second.fetch.pk,
                first.fetch.pk,
            ],
        )
        self.assertEqual(delta.old, "Old B\n\n---\n\nOld A\n\n---\n\nGone")
        self.assertEqual(delta.new, "New wiki\n\n---\n\nNew B\n\n---\n\nNew A")
        self.assertIn("--- sources_old", delta.diff)
        self.assertIn("+++ sources_new", delta.diff)
        self.assertIn("-Gone", delta.diff)
        self.assertIn("+New wiki", delta.diff)

    def test_runner_exposes_numbered_readonly_files_and_edits_current(self):
        source = self.source(GameSource.SourceType.IFWIKI, "Old", "New")
        self.state.sources = [source]
        responses = []
        for index, (name, args) in enumerate(
            (
                (
                    "replace_lines",
                    {
                        "start_line": 1,
                        "end_line": 1,
                        "text": "New",
                        "rationale": "update",
                    },
                ),
                ("finish", {"resolution": "commit", "summary": "Done"}),
            ),
            1,
        ):
            responses.append({
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{index}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            })
        with patch.object(
            openrouter, "chat_completion", side_effect=responses
        ) as chat:
            self.assertIsNotNone(
                runner_for_workflow(self.workflow, self.state).run()
            )

        prompt = chat.call_args_list[0].args[1][0]["content"]
        for excerpt in (
            "FILE: current [editable]\n1: Old\n2: Human note",
            "FILE: sources_old [readonly]\n1: Old",
            "FILE: sources_new [readonly]\n1: New",
            "FILE: sources_diff [readonly]",
        ):
            self.assertIn(excerpt, prompt)
        self.assertIn("-Old", prompt)
        self.assertIn("+New", prompt)
        self.assertEqual(self.state.current.description, "New\nHuman note")
        self.assertEqual(
            self.state.source_snapshots,
            {
                "old": [source.previous_fetch.pk],
                "new": [source.fetch.pk],
            },
        )

    def test_equal_merged_descriptions_skip_agent_even_with_changed_metadata(
        self,
    ):
        source = self.source(
            GameSource.SourceType.IFWIKI,
            "Same",
            "Same",
            old_name="Before",
            new_name="After",
        )
        self.state.sources = [source]
        with patch.object(openrouter, "chat_completion") as chat:
            self.assertIsNone(
                runner_for_workflow(self.workflow, self.state).run()
            )
        chat.assert_not_called()
        self.assertEqual(self.state.source_snapshots, {"old": [], "new": []})
        self.assertFalse(LlmTrajectory.objects.exists())


class UpdateDescriptionSeedTests(TestCase):
    def test_workflow_is_seeded_without_pipeline_changes(self):
        workflow = LlmWorkflow.objects.get(name="update_description")
        self.assertEqual(workflow.runner, "update_description")
        self.assertEqual(workflow.model.name, "google/gemma-4-26b-a4b-it")
        self.assertIn("{{ numbered_files }}", workflow.prompt_template)
        self.assertIn(
            "apply the semantic change from `sources_old` to `sources_new`",
            workflow.prompt_template,
        )
        self.assertFalse(
            EditPipeline.objects.filter(
                passes__contains=[
                    {"name": "llm_workflow", "workflow": "update_description"}
                ]
            ).exists()
        )
