import json
import logging
import re
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.template import Context, Template
from django.utils.timezone import now

from curation import openrouter
from curation.models import LlmTrajectory, LlmWorkflow
from games.models import Game
from play.models import Playable

logger = logging.getLogger("worker")

RESERVED_SUBDOMAINS: set[str] = {
    "www",
    "api",
    "admin",
    "play",
    "mail",
    "staging",
    "dev",
    "static",
    "media",
    "caddy",
    "localhost",
    "test",
}

_SLUG_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

SUGGEST_NAMES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "suggest_names",
        "description": (
            "Check candidate domain names / slugs to see if they are "
            "available or already busy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of candidate subdomain names in order of "
                        "preference."
                    ),
                }
            },
            "required": ["names"],
        },
    },
}


def is_valid_domain_slug(slug: str) -> bool:
    normalized = slug.strip()
    if not normalized or len(normalized) > 63:
        return False
    if normalized != normalized.lower():
        return False
    if "--" in normalized:
        return False
    return bool(_SLUG_REGEX.match(normalized))


def is_domain_busy(
    slug: str, current_playable_pk: int | None = None
) -> tuple[bool, str]:
    normalized = slug.strip().lower()
    if not is_valid_domain_slug(normalized):
        return (
            True,
            "Invalid format: only lowercase latin letters, digits, and "
            "hyphens allowed (no leading/trailing hyphens, no consecutive "
            "hyphens).",
        )
    if normalized in RESERVED_SUBDOMAINS:
        return True, f"'{normalized}' is a reserved subdomain."

    qs = Playable.objects.filter(slug=normalized)
    if current_playable_pk is not None:
        qs = qs.exclude(pk=current_playable_pk)
    if qs.exists():
        return True, f"'{normalized}' is already in use by another game."

    return False, ""


def check_suggested_names(
    names: list[str], current_playable_pk: int | None = None
) -> tuple[dict[str, Any], str | None]:
    results: dict[str, dict[str, Any]] = {}
    selected: str | None = None
    for raw_name in names:
        candidate = raw_name.strip().lower()
        busy, reason = is_domain_busy(candidate, current_playable_pk)
        if busy:
            results[candidate] = {"available": False, "reason": reason}
        else:
            results[candidate] = {"available": True}
            if selected is None:
                selected = candidate

    message = (
        f"Selected available domain: '{selected}'."
        if selected
        else (
            "All suggested names are busy or invalid. "
            "Please suggest alternative names."
        )
    )
    payload = {
        "results": results,
        "selected": selected,
        "message": message,
    }
    return payload, selected


def generate_playable_domain(
    game: Game,
    current_playable_pk: int | None = None,
    max_steps: int = 5,
) -> str:
    workflow = LlmWorkflow.objects.get(name="playable_domain")
    model = workflow.model
    prompt_content = Template(workflow.prompt_template).render(
        Context(
            {
                "game": game,
                "base_domain": settings.PLAYABLE_BASE_DOMAIN,
            },
            autoescape=False,
        )
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt_content}
    ]
    tools = [SUGGEST_NAMES_TOOL]
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
    }
    selected_slug: str | None = None

    try:
        for _ in range(max_steps):
            response = openrouter.chat_completion(
                model.name,
                messages,
                tools=tools,
                tool_choice="required",
            )
            resp_usage = response.get("usage") or {}
            usage["prompt_tokens"] += resp_usage.get("prompt_tokens") or 0
            usage["completion_tokens"] += (
                resp_usage.get("completion_tokens") or 0
            )
            details = resp_usage.get("prompt_tokens_details") or {}
            usage["cached_input_tokens"] += details.get("cached_tokens") or 0
            usage["cache_write_tokens"] += (
                details.get("cache_write_tokens") or 0
            )

            choices = response.get("choices") or []
            if not choices:
                break
            message = choices[0]["message"]
            messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break

            for call in tool_calls:
                function_data = call.get("function") or {}
                fn_name = function_data.get("name")
                args_str = function_data.get("arguments") or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}

                if fn_name == "suggest_names":
                    names = args.get("names") or []
                    if not isinstance(names, list):
                        names = [str(names)]
                    payload, chosen = check_suggested_names(
                        names, current_playable_pk
                    )
                    if chosen and selected_slug is None:
                        selected_slug = chosen
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": fn_name,
                        "content": json.dumps(payload, ensure_ascii=False),
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": fn_name or "unknown",
                        "content": json.dumps({
                            "error": f"Unknown tool: {fn_name}"
                        }),
                    })

            if selected_slug:
                break
    finally:
        if messages and len(messages) > 1:
            try:
                LlmTrajectory.objects.create(
                    game=game,
                    workflow=workflow,
                    model=model,
                    created_at=now(),
                    messages=messages,
                    prompt_tokens=usage["prompt_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    cache_write_tokens=usage["cache_write_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    cost=model.cost_for(
                        usage["prompt_tokens"],
                        usage["cached_input_tokens"],
                        usage["cache_write_tokens"],
                        usage["completion_tokens"],
                    ).quantize(Decimal("0.000001")),
                )
            except Exception:
                logger.exception(
                    "Failed to save LlmTrajectory for domain generation for "
                    "game #%s",
                    game.pk,
                )

    if not selected_slug:
        raise RuntimeError(
            f"LLM failed to select an available domain name for "
            f"game #{game.pk}"
        )

    return selected_slug
