from decimal import Decimal

from django.test import TestCase

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
