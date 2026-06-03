import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any, ClassVar, get_args, get_origin

from django.template import Context, Template
from django.utils.timezone import now

from . import openrouter
from .edit import GameEditState
from .models import LlmTrajectory, LlmWorkflow

LLM_RUNNERS: dict[str, type["LlmWorkflowRunner"]] = {}


def register_llm_runner(cls: type["LlmWorkflowRunner"]):
    LLM_RUNNERS[cls.runner_name] = cls
    return cls


def runner_for_workflow(
    workflow: LlmWorkflow, state: GameEditState
) -> "LlmWorkflowRunner":
    try:
        cls = LLM_RUNNERS[workflow.runner]
    except KeyError as e:
        raise ValueError(
            f"LLM workflow {workflow.name!r} uses unknown runner "
            f"{workflow.runner!r}"
        ) from e
    return cls(workflow, state)


def _json_schema(annotation) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation in (inspect.Signature.empty, str):
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    if annotation is list or origin is list:
        items = _json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}
    raise TypeError(f"Unsupported LLM tool annotation: {annotation!r}")


class LlmWorkflowRunner(ABC):
    runner_name: ClassVar[str]

    def __init__(self, workflow: LlmWorkflow, state: GameEditState):
        if workflow.runner != self.runner_name:
            raise ValueError(
                f"Workflow {workflow.name!r} uses runner {workflow.runner!r}, "
                f"not {self.runner_name!r}"
            )
        self.workflow = workflow
        self.state = state
        self.model = workflow.model

    @abstractmethod
    def run(self) -> LlmTrajectory:
        pass

    def run_agent_loop(
        self, context: dict[str, Any], *, max_steps: int = 8
    ) -> LlmTrajectory:
        messages = [
            {
                "role": "user",
                "content": Template(self.workflow.prompt_template).render(
                    Context(context)
                ),
            }
        ]
        tools = self._tools_schema()
        tool_methods = self._tool_methods()
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
        }

        for _ in range(max_steps):
            response = openrouter.chat_completion(
                self.model.name, messages, tools=tools
            )
            self._add_usage(usage, response.get("usage") or {})
            message = response["choices"][0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break
            for call in tool_calls:
                messages.append(self._run_tool_call(call, tool_methods))

        return LlmTrajectory.objects.create(
            history=self.state.history,
            workflow=self.workflow,
            model=self.model,
            created_at=now(),
            messages=messages,
            prompt_tokens=usage["prompt_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            cache_write_tokens=usage["cache_write_tokens"],
            completion_tokens=usage["completion_tokens"],
            cost=self.model.cost_for(
                usage["prompt_tokens"],
                usage["cached_input_tokens"],
                usage["cache_write_tokens"],
                usage["completion_tokens"],
            ).quantize(Decimal("0.000001")),
        )

    def _tool_methods(self) -> dict[str, Callable]:
        tools = {}
        for name in self.workflow.allowed_tools:
            method = getattr(self, name, None)
            if method is None or name.startswith("_"):
                raise ValueError(
                    f"Workflow {self.workflow.name!r} allows unknown tool "
                    f"{name!r}"
                )
            tools[name] = method
        return tools

    def _tools_schema(self) -> list[dict[str, Any]]:
        return [
            self._tool_schema(name, method)
            for name, method in self._tool_methods().items()
        ]

    def _tool_schema(self, name: str, method: Callable) -> dict[str, Any]:
        signature = inspect.signature(method)
        properties = {}
        required = []
        for param in signature.parameters.values():
            if param.kind not in (
                param.POSITIONAL_OR_KEYWORD,
                param.KEYWORD_ONLY,
            ):
                raise TypeError(f"Unsupported LLM tool parameter: {param}")
            properties[param.name] = _json_schema(param.annotation)
            if param.default is inspect.Signature.empty:
                required.append(param.name)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": inspect.getdoc(method) or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _run_tool_call(
        self, call: dict[str, Any], tool_methods: dict[str, Callable]
    ) -> dict[str, Any]:
        function = call["function"]
        name = function["name"]
        method = tool_methods[name]
        args = json.loads(function.get("arguments") or "{}")
        result = method(**args)
        return {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": name,
            "content": str(result),
        }

    def _add_usage(self, total: dict[str, int], usage: dict[str, Any]) -> None:
        total["prompt_tokens"] += usage.get("prompt_tokens") or 0
        total["completion_tokens"] += usage.get("completion_tokens") or 0
        details = usage.get("prompt_tokens_details") or {}
        total["cached_input_tokens"] += details.get("cached_tokens") or 0
        total["cache_write_tokens"] += details.get("cache_write_tokens") or 0


# Imported for registration side effects: each runner populates LLM_RUNNERS via
# @register_llm_runner on import.
from . import llm_runners  # noqa: E402,F401
