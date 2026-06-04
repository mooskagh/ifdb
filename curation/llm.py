import inspect
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from decimal import Decimal
from types import UnionType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from django.template import Context, Template
from django.utils.timezone import now

from . import openrouter
from .edit import GameEditState
from .models import LlmTrajectory, LlmWorkflow

LLM_RUNNERS: dict[str, type["LlmWorkflowRunner"]] = {}
DEFAULT_MAX_STEPS = 100
DEFAULT_MAX_ERROR_TOOL_CALLS = 20


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
    return cls(workflow, state, **workflow.runner_params)


def llm_tool(method: Callable) -> Callable:
    method.llm_tool = True
    return method


def _json_schema(annotation) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        schema = _json_schema(args[0])
        if len(args) > 1 and isinstance(args[1], str):
            schema["description"] = args[1]
        return schema
    if origin is Literal:
        values = list(args)
        schema = _json_schema(type(values[0])) if values else {}
        schema["enum"] = values
        return schema
    if _is_optional(annotation):
        return _json_schema(_optional_type(annotation))
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
    if is_dataclass(annotation):
        return _dataclass_schema(annotation)
    raise TypeError(f"Unsupported LLM tool annotation: {annotation!r}")


def _is_optional(annotation) -> bool:
    origin = get_origin(annotation)
    return origin in (UnionType, Union) and type(None) in get_args(annotation)


def _optional_type(annotation):
    return next(arg for arg in get_args(annotation) if arg is not type(None))


def _dataclass_schema(cls) -> dict[str, Any]:
    properties = {}
    required = []
    type_hints = get_type_hints(cls, include_extras=True)
    for field in fields(cls):
        annotation = type_hints[field.name]
        properties[field.name] = _json_schema(annotation)
        if (
            not _is_optional(annotation)
            and field.default is MISSING
            and field.default_factory is MISSING
        ):
            required.append(field.name)
    return {"type": "object", "properties": properties, "required": required}


def _coerce_tool_arg(annotation, value):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _coerce_tool_arg(args[0], value)
    if _is_optional(annotation):
        if value is None:
            return None
        return _coerce_tool_arg(_optional_type(annotation), value)
    if is_dataclass(annotation):
        if not isinstance(value, dict):
            raise TypeError(
                f"Expected object for LLM tool argument {annotation!r}"
            )
        hints = get_type_hints(annotation, include_extras=True)
        return annotation(**{
            field.name: _coerce_tool_arg(hints[field.name], value[field.name])
            for field in fields(annotation)
            if field.name in value
        })
    if origin is list:
        item_type = args[0] if args else Any
        return [_coerce_tool_arg(item_type, item) for item in value]
    if origin is dict:
        value_type = args[1] if len(args) > 1 else Any
        return {
            key: _coerce_tool_arg(value_type, item)
            for key, item in value.items()
        }
    return value


class LlmWorkflowRunner(ABC):
    runner_name: ClassVar[str]

    def __init__(self, workflow: LlmWorkflow, state: GameEditState, **params):
        if workflow.runner != self.runner_name:
            raise ValueError(
                f"Workflow {workflow.name!r} uses runner {workflow.runner!r}, "
                f"not {self.runner_name!r}"
            )
        self.workflow = workflow
        self.state = state
        self.model = workflow.model
        self.params = params
        self.stop_reason: str | None = None

    @abstractmethod
    def run(self) -> LlmTrajectory:
        pass

    def run_agent_loop(
        self,
        context: dict[str, Any],
        *,
        max_steps: int | None = None,
        max_error_tool_calls: int | None = None,
        require_tool: bool | None = None,
    ) -> LlmTrajectory:
        max_steps = max_steps or self.params.get(
            "max_steps", DEFAULT_MAX_STEPS
        )
        max_error_tool_calls = max_error_tool_calls or self.params.get(
            "max_error_tool_calls", DEFAULT_MAX_ERROR_TOOL_CALLS
        )
        require_tool = (
            self.params.get("require_tool", False)
            if require_tool is None
            else require_tool
        )
        messages = [
            {
                "role": "user",
                "content": Template(self.workflow.prompt_template).render(
                    Context(context, autoescape=False)
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
        error_tool_calls = 0
        missing_tool_calls = 0

        for _ in range(max_steps):
            response = openrouter.chat_completion(
                self.model.name,
                messages,
                tools=tools,
                tool_choice="required" if require_tool and tools else None,
            )
            self._add_usage(usage, response.get("usage") or {})
            message = response["choices"][0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                if require_tool and tools:
                    missing_tool_calls += 1
                    if missing_tool_calls >= max_error_tool_calls:
                        self.stop_reason = "missing_tool_calls"
                        break
                    continue
                break
            tool_results = []
            for call in tool_calls:
                tool_result = self._run_tool_call(call, tool_methods)
                tool_results.append(tool_result)
                messages.append(tool_result)
                if _is_error_tool_result(tool_result):
                    error_tool_calls += 1
            if self.should_stop(message, tool_results, len(messages)):
                break
            if error_tool_calls >= max_error_tool_calls:
                self.stop_reason = "max_error_tool_calls"
                break

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

    def tools(self) -> dict[str, Callable]:
        return {
            name: method
            for name in dir(self)
            if not name.startswith("_")
            and getattr(method := getattr(self, name), "llm_tool", False)
        }

    def _tools_schema(self) -> list[dict[str, Any]]:
        return [
            self._tool_schema(name, method)
            for name, method in self.tools().items()
        ]

    def _tool_methods(self) -> dict[str, Callable]:
        return self.tools()

    def _tool_schema(self, name: str, method: Callable) -> dict[str, Any]:
        signature = inspect.signature(method)
        params = list(signature.parameters.values())
        if len(params) != 1:
            raise TypeError(
                f"LLM tool {name!r} must have one dataclass parameter"
            )
        param = params[0]
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            raise TypeError(f"Unsupported LLM tool parameter: {param}")
        if not is_dataclass(param.annotation):
            raise TypeError(f"LLM tool {name!r} parameter must be a dataclass")
        parameters = _dataclass_schema(param.annotation)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": inspect.getdoc(method) or "",
                "parameters": parameters,
            },
        }

    def _run_tool_call(
        self, call: dict[str, Any], tool_methods: dict[str, Callable]
    ) -> dict[str, Any]:
        function = call["function"]
        name = function["name"]
        method = tool_methods[name]
        param_cls = next(
            iter(inspect.signature(method).parameters.values())
        ).annotation
        args = json.loads(function.get("arguments") or "{}")
        result = method(_coerce_tool_arg(param_cls, args))
        if not isinstance(result, dict):
            raise TypeError(f"LLM tool {name!r} must return dict")
        return {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": name,
            "content": json.dumps(result, ensure_ascii=False),
        }

    def should_stop(
        self,
        message: dict[str, Any],
        tool_results: list[dict[str, Any]],
        step: int,
    ) -> bool:
        return not message.get("tool_calls")

    def _add_usage(self, total: dict[str, int], usage: dict[str, Any]) -> None:
        total["prompt_tokens"] += usage.get("prompt_tokens") or 0
        total["completion_tokens"] += usage.get("completion_tokens") or 0
        details = usage.get("prompt_tokens_details") or {}
        total["cached_input_tokens"] += details.get("cached_tokens") or 0
        total["cache_write_tokens"] += details.get("cache_write_tokens") or 0


def _is_error_tool_result(message: dict[str, Any]) -> bool:
    if message.get("role") != "tool":
        return False
    try:
        content = json.loads(message.get("content") or "{}")
    except json.JSONDecodeError:
        return False
    return content.get("status") == "error"


# Imported for registration side effects: each runner populates LLM_RUNNERS via
# @register_llm_runner on import.
from . import llm_runners  # noqa: E402,F401
