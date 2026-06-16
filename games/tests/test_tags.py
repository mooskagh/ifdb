from decimal import Decimal

from django.test import SimpleTestCase

from games.templatetags.tags import costcell


class CostCellTests(SimpleTestCase):
    def test_strips_trailing_zeros_keeping_alignment_padding(self):
        # "12,5000" → visible "12,5", the trailing zeros hidden for alignment.
        self.assertEqual(
            costcell(Decimal("12.5")), '12,5<span class="zeros">000</span>'
        )

    def test_whole_number_hides_entire_fraction(self):
        self.assertEqual(
            costcell(Decimal("0")), '0<span class="zeros">,0000</span>'
        )

    def test_no_trailing_zeros_renders_plainly(self):
        self.assertEqual(costcell(Decimal("0.0833")), "0,0833")

    def test_long_decimal_is_quantized(self):
        self.assertEqual(costcell(Decimal("0.08333333333333334")), "0,0833")

    def test_negative_and_none_show_em_dash(self):
        self.assertEqual(costcell(Decimal("-1000000")), "—")
        self.assertEqual(costcell(None), "—")
