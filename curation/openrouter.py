"""Minimal OpenRouter catalog client for populating LLMModel rows."""

from decimal import Decimal
from logging import getLogger

import requests
from django.conf import settings

MODELS_URL = "https://openrouter.ai/api/v1/models"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
logger = getLogger("worker")

_MTOK = Decimal(1_000_000)

# OpenRouter pricing key -> LLMModel field. Prices are $/token strings;
# we scale them to $/Mtok. Cache fields are often absent (default 0).
_PRICING_FIELDS = {
    "prompt": "input_cost",
    "completion": "output_cost",
    "input_cache_read": "cached_input_cost",
    "input_cache_write": "cache_write_cost",
}


def fetch_models() -> list[dict]:
    """Return the OpenRouter `/models` catalog (the `data` list)."""
    response = requests.get(MODELS_URL, headers=_headers())
    response.raise_for_status()
    return response.json().get("data", [])


def _headers() -> dict[str, str]:
    headers = {}
    if settings.OPENROUTER_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OPENROUTER_API_KEY}"
    return headers


def chat_completion(
    model: str, messages: list[dict], tools=None, tool_choice=None
) -> dict:
    payload = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    response = requests.post(CHAT_URL, json=payload, headers=_headers())
    try:
        response.raise_for_status()
    except requests.HTTPError:
        logger.exception(
            "OpenRouter chat completion HTTP error for model %r: status=%s "
            "body=%s",
            model,
            response.status_code,
            _short_text(response.text),
        )
        raise
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        logger.error(
            "OpenRouter chat completion error for model %r: %s",
            model,
            _short_text(data["error"]),
        )
        raise ValueError(f"OpenRouter error: {_short_text(data['error'])}")
    return data


def model_fields(entry: dict) -> dict:
    """Map one OpenRouter catalog entry to LLMModel kwargs."""
    pricing = entry.get("pricing", {})
    fields = {
        field: Decimal(str(pricing.get(key, 0))) * _MTOK
        for key, field in _PRICING_FIELDS.items()
    }
    fields["name"] = entry["id"]
    fields["context_length"] = entry.get("context_length") or 0
    return fields


# Illustrative token profile of one curation run, for the "$/game" estimate:
# a small paragraph ≈ 75 tokens; an initial 20-paragraph prompt, then 5
# iterations that each add one paragraph both ways with the whole conversation
# re-sent every turn (input grows by 2 paragraphs/turn). Six model turns:
#   input  = 75 * (20 + 22 + 24 + 26 + 28 + 30) = 11250
#   output = 75 * 6                             = 450
TYPICAL_PROMPT_TOKENS = 11_250
TYPICAL_COMPLETION_TOKENS = 450


def typical_cents(input_cost, output_cost):
    """Illustrative ¢ to curate one game; None when pricing is variable (<0).

    OpenRouter prices auto-router models as `-1` ($/Mtok `-1_000_000`), meaning
    "depends on the model picked" — there's no meaningful per-game figure.
    """
    if input_cost < 0 or output_cost < 0:
        return None
    dollars = (
        input_cost * TYPICAL_PROMPT_TOKENS
        + output_cost * TYPICAL_COMPLETION_TOKENS
    ) / _MTOK
    return dollars * 100


def _short_text(value) -> str:
    text = str(value)
    if len(text) > 1000:
        text = text[:997] + "..."
    return text
