import unittest
from datetime import datetime, timedelta

from lib.mobile_stocktake import (
    find_prewrite_drift,
    find_reservation_conflicts,
    find_verification_mismatches,
    index_live_rows,
    inspect_live_row_issues,
    plan_stocktake_updates,
)


class MobileStocktakePlanningTests(unittest.TestCase):
    def test_stale_display_f_by_two_uses_live_f_for_recalculation(self):
        # 画面表示時は F=10/G=20。その後の売上で F だけが8へ変化した想定。
        # 実棚卸10へ合わせるには、表示時FではなくライブFとの差2をGへ加える。
        live = index_live_rows([
            ["SKU-1", "商品", "", "", "", 8, 20],
        ])

        plan = plan_stocktake_updates(
            [("SKU-1", 10)],
            {"SKU-1": 20},
            live,
            add_mode=False,
        )

        self.assertEqual(plan.conflicts, ())
        self.assertEqual(len(plan.changes), 1)
        change = plan.changes[0]
        self.assertEqual(change.f_before, 8)
        self.assertEqual(change.f_after, 10)
        self.assertEqual(change.g_before, 20)
        self.assertEqual(change.g_after, 22)

    def test_changed_live_g_blocks_stale_screen_update(self):
        live = index_live_rows([
            ["SKU-1", "商品", "", "", "", 8, 21],
        ])

        plan = plan_stocktake_updates(
            [("SKU-1", 10)],
            {"SKU-1": 20},
            live,
            add_mode=False,
        )

        self.assertEqual(plan.changes, ())
        self.assertEqual(plan.conflicts, ("SKU-1",))

    def test_verification_requires_both_f_and_g(self):
        before = index_live_rows([
            ["SKU-1", "商品", "", "", "", 8, 20],
        ])
        change = plan_stocktake_updates(
            [("SKU-1", 10)], {"SKU-1": 20}, before, add_mode=False
        ).changes

        f_not_recalculated = index_live_rows([
            ["SKU-1", "商品", "", "", "", 8, 22],
        ])
        self.assertEqual(
            find_verification_mismatches(change, f_not_recalculated),
            ("SKU-1",),
        )

        fully_applied = index_live_rows([
            ["SKU-1", "商品", "", "", "", 10, 22],
        ])
        self.assertEqual(find_verification_mismatches(change, fully_applied), ())

    def test_duplicate_or_formula_error_blocks_only_affected_sku(self):
        rows = [
            ["DUP", "商品", "", "", "", 3, 3],
            ["DUP", "商品", "", "", "", 3, 3],
            ["BAD", "商品", "", "", "", "#N/A", 2],
            ["OK", "商品", "", "", "", 4, 4],
        ]
        duplicates, invalid = inspect_live_row_issues(rows)
        live = index_live_rows(rows)
        plan = plan_stocktake_updates(
            [("DUP", 2), ("BAD", 2), ("OK", 5)],
            {"DUP": 3, "BAD": 2, "OK": 4},
            live,
            add_mode=False,
            blocked_skus=set(duplicates) | set(invalid),
        )
        self.assertEqual(set(plan.conflicts), {"DUP", "BAD"})
        self.assertEqual([change.sku for change in plan.changes], ["OK"])

    def test_first_live_reservation_wins_across_devices(self):
        now = datetime(2026, 10, 2, 12, 0, 0)
        rows = [
            [(now - timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S"),
             "モバイル棚卸予約", "SKU-1", "", "", "BATCH-A:001", "予約中", ""],
            [now.strftime("%Y-%m-%d %H:%M:%S"),
             "モバイル棚卸予約", "SKU-1", "", "", "BATCH-B:001", "予約中", ""],
        ]
        self.assertEqual(
            find_reservation_conflicts(rows, "BATCH-B", ["SKU-1"], now=now),
            ("SKU-1",),
        )
        self.assertEqual(
            find_reservation_conflicts(rows, "BATCH-A", ["SKU-1"], now=now),
            (),
        )

    def test_completed_other_batch_cannot_make_stale_plan_overwrite(self):
        before = index_live_rows([
            ["SKU-1", "商品", "", "", "", 8, 20],
        ])
        changes = plan_stocktake_updates(
            [("SKU-1", 10)], {"SKU-1": 20}, before, add_mode=False
        ).changes

        # 別端末が予約から完了まで終えた直後。予約ロック自体は解放済みでも、
        # 古い変更前F/Gと一致しないため書込直前検査で止める。
        after_other_device = index_live_rows([
            ["SKU-1", "商品", "", "", "", 11, 23],
        ])
        self.assertEqual(
            find_prewrite_drift(changes, after_other_device),
            ("SKU-1",),
        )
        self.assertEqual(find_prewrite_drift(changes, before), ())


if __name__ == "__main__":
    unittest.main()
