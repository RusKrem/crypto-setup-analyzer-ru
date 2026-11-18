import unittest

from ui.rebound_scanner_window import ReboundScannerWindow


class FakeTree:
    def __init__(self, row):
        self.rows = {"row1": dict(row)}
        self.tags = {}

    def exists(self, item_id):
        return item_id in self.rows

    def set(self, item_id, column):
        return self.rows[item_id][column]

    def item(self, item_id, option=None, **kwargs):
        if kwargs:
            self.rows[item_id].update(kwargs)
        if option == "values":
            return self.rows[item_id]["values"]
        return self.rows[item_id]

    def tag_configure(self, tag, **kwargs):
        self.tags[tag] = kwargs

    def get_children(self, _parent):
        return list(self.rows)

    def move(self, *_args):
        pass


class ReboundScannerWindowTests(unittest.TestCase):
    def test_live_price_update_preserves_confirmed_reaction(self):
        key = ("TESTUSDT", "PDH")
        previous_values = (
            "2026-11-18 12:00:00", "TESTUSDT", "Предыдущий день", "PDH",
            "100", "99.2", "0.800%", "→ Без изменений",
            "РЕАКЦИЯ ПОДТВЕРЖДЕНА", "Отвержение: тень/тело 2.10"
        )
        table = FakeTree({
            "values": previous_values,
            "status": "РЕАКЦИЯ ПОДТВЕРЖДЕНА",
            "details": "Отвержение: тень/тело 2.10",
            "tags": ("CONFIRMED",),
        })
        window = ReboundScannerWindow.__new__(ReboundScannerWindow)
        window.table = table
        window._row_ids = {key: "row1"}
        window._last_distances = {}

        window.update_price({
            "symbol": "TESTUSDT",
            "level_name": "PDH",
            "level_group": "Предыдущий день",
            "level": 100.0,
            "price": 99.4,
            "distance_pct": 0.6,
            "time": 1_794_000_000_000,
            "in_zone": False,
        })

        values = table.rows["row1"]["values"]
        self.assertEqual(values[8], "РЕАКЦИЯ ПОДТВЕРЖДЕНА")
        self.assertEqual(values[9], "Отвержение: тень/тело 2.10")
        self.assertEqual(values[5], "99.4")
        self.assertEqual(table.rows["row1"]["tags"], ("CONFIRMED",))


if __name__ == "__main__":
    unittest.main()
