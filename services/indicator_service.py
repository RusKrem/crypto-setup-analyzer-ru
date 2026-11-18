"""Сервис расчёта индикаторов. Содержит оркестрацию, но не код отрисовки."""
from crypto_setup_analyzer import analysis


class IndicatorService:
    """Фасад над чистыми функциями анализа рынка."""

    def add_levels(self, candles):
        return analysis.add_levels(candles)

    def calculate_reference_levels(self, candles):
        return analysis.calculate_reference_levels(candles)

    def retain_live_history_depth(self, combined, previous_count):
        return analysis.retain_live_history_depth(combined, previous_count)

    def find_events(self, candles):
        return analysis.find_events(candles)

    def find_price_reactions(self, candles):
        return analysis.find_price_reactions(candles)

    def find_order_blocks(self, candles):
        return analysis.find_order_blocks(candles)

    def find_market_structure(self, candles, pivot_window=5, max_pivots=100):
        return analysis.find_market_structure(candles, pivot_window=pivot_window, max_pivots=max_pivots)
