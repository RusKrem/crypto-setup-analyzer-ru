"""Единая модель торгового сигнала."""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    level_name: str
    level: float
    price: float
    time: int
    details: str = ""

    def to_dict(self):
        """Преобразует сигнал в словарь для интерфейса и хранения."""
        return asdict(self)
