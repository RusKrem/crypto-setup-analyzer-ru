"""Единая модель виртуальной сделки."""
from dataclasses import dataclass, asdict

@dataclass
class VirtualTrade:
    trade_id: str
    symbol: str
    direction: str
    signal_time: int
    entry: float
    stop: float
    target: float
    level_name: str
    level: float
    status: str = "OPEN"
    exit_price: float | None = None
    exit_time: int | None = None
    result_pct: float | None = None

    def to_dict(self):
        """Преобразует сделку в словарь для интерфейса и хранения."""
        return asdict(self)
