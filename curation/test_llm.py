from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from . import openrouter
from .models import LLMModel


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
