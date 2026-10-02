"""公開モバイルアプリ側の共有在庫更新ロック回帰テスト。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from lib import inventory_mutation_lock as lockmod


NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)


def _active(owner, expires):
    return [owner, "入荷反映", lockmod.ACTIVE, lockmod._iso(NOW), lockmod._iso(expires), "", "pc", ""]


class _Worksheet:
    def __init__(self, rows=None):
        self.rows = rows or [list(lockmod.HEADERS)]
        self.updated = []

    def get_all_values(self):
        return [list(row) for row in self.rows]

    def append_row(self, values, value_input_option=None):
        self.rows.append(list(values))

    def update(self, range_name=None, values=None, value_input_option=None):
        row_number = int(range_name.split(":", 1)[0][1:])
        while len(self.rows) < row_number:
            self.rows.append([])
        self.rows[row_number - 1] = list(values[0])
        self.updated.append(range_name)


class _Spreadsheet:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, name):
        self.asserted_name = name
        return self.ws


class InventoryMutationLockTests(unittest.TestCase):
    def test_simultaneous_append_oldest_wins(self):
        ws = _Worksheet([list(lockmod.HEADERS), _active("first", NOW + timedelta(minutes=5))])
        with self.assertRaises(lockmod.InventoryMutationLockBusy):
            lockmod.acquire_inventory_mutation_lock(
                _Spreadsheet(ws), purpose="モバイル棚卸", owner="mine", now=NOW
            )
        self.assertEqual(lockmod.RELEASED, ws.rows[2][2])

    def test_expired_row_does_not_block(self):
        ws = _Worksheet([list(lockmod.HEADERS), _active("old", NOW - timedelta(seconds=1))])
        acquired = lockmod.acquire_inventory_mutation_lock(
            _Spreadsheet(ws), purpose="モバイル棚卸", owner="mine", now=NOW
        )
        self.assertEqual("mine", acquired.owner)

    def test_release_marks_own_row(self):
        ws = _Worksheet()
        acquired = lockmod.acquire_inventory_mutation_lock(
            _Spreadsheet(ws), purpose="モバイル棚卸", owner="mine", now=NOW
        )
        with patch.object(lockmod, "_utc_now", return_value=NOW + timedelta(seconds=1)):
            acquired.release(note="完了")
        self.assertEqual(lockmod.RELEASED, ws.rows[1][2])
        self.assertEqual("完了", ws.rows[1][7])


if __name__ == "__main__":
    unittest.main()
