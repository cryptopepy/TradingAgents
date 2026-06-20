"""Tests for simplified liquidation price estimates."""

from __future__ import annotations

import unittest

from tradingagents.simulator.liquidation import (
    estimate_liquidation_price,
    format_liquidation_cell,
    leverage_display_tiers,
)


class TestLiquidationEstimates(unittest.TestCase):
    def test_long_liquidation_below_entry(self):
        entry = 60_000.0
        liq = estimate_liquidation_price(entry, 2.0, "long", maintenance_margin=0.0)
        self.assertAlmostEqual(liq, 30_000.0)

    def test_short_liquidation_above_entry(self):
        entry = 60_000.0
        liq = estimate_liquidation_price(entry, 2.0, "short", maintenance_margin=0.0)
        self.assertAlmostEqual(liq, 90_000.0)

    def test_maintenance_margin_raises_long_liq(self):
        entry = 60_000.0
        bare = estimate_liquidation_price(entry, 3.0, "long", maintenance_margin=0.0)
        buffered = estimate_liquidation_price(entry, 3.0, "long", maintenance_margin=0.005)
        self.assertIsNotNone(bare)
        self.assertIsNotNone(buffered)
        self.assertGreater(buffered, bare)

    def test_no_leverage_returns_none(self):
        self.assertIsNone(estimate_liquidation_price(60_000.0, 1.0, "long"))

    def test_leverage_tiers_include_session(self):
        self.assertEqual(leverage_display_tiers(2.0), [2.0, 3.0])
        self.assertEqual(leverage_display_tiers(5.0), [2.0, 3.0, 5.0])

    def test_format_cell_open_long(self):
        cell = format_liquidation_cell(60_000.0, 2.0, position_side="long", maintenance_margin=0.0)
        self.assertEqual(cell, "$30,000")

    def test_format_cell_flat_shows_both(self):
        cell = format_liquidation_cell(60_000.0, 2.0, position_side=None, maintenance_margin=0.0)
        self.assertIn("↓$30,000", cell)
        self.assertIn("↑$90,000", cell)


if __name__ == "__main__":
    unittest.main()
