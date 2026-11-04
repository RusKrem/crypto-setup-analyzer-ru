import unittest
import pandas as pd
from crypto_setup_analyzer.swing_backtest import confirmed_structure, backtest_hh_ll

class SwingBacktestTests(unittest.TestCase):
    def candles(self):
        # Волны с однозначными локальными максимумами и минимумами.
        close = [10, 11, 13, 12, 10, 8, 9, 12, 15, 13, 10, 7, 9, 12, 16, 14, 11, 6, 8, 12, 14]
        rows = []
        for i, c in enumerate(close):
            rows.append({"timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15*i),
                         "open": c-0.2, "high": c+0.5, "low": c-0.5, "close": c, "volume": 100})
        return pd.DataFrame(rows)

    def test_confirmation_is_delayed(self):
        df = self.candles()
        pivots = confirmed_structure(df, pivot_window=2)
        self.assertTrue((pivots.confirmed_index == pivots.pivot_index + 2).all())
        self.assertTrue(set(pivots.label).issubset({"HH", "LH", "HL", "LL"}))

    def test_backtest_outputs_metrics_and_ignores_hl_lh_as_signals(self):
        trades, summary, structure = backtest_hh_ll(self.candles(), pivot_window=2, fee_pct=0, slippage_pct=0)
        self.assertIn("Сделок закрыто", summary)
        self.assertTrue(set(structure.label).issubset({"HH", "LH", "HL", "LL"}))
        self.assertTrue(len(trades) >= 1)
        self.assertTrue(set(trades["Направление"]).issubset({"LONG", "SHORT"}))

if __name__ == "__main__":
    unittest.main()
