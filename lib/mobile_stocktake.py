"""モバイル棚卸の競合検知・在庫逆算を行う純粋関数。

Streamlit や Google Sheets に依存させず、送信時のライブ値だけを基準に
更新内容を決める。画面表示後に売上で F だけが動いても追従し、G が別処理で
変わった場合は古い画面から上書きしない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Iterable, Mapping, Sequence


def as_int(value) -> int:
    """Google Sheets の数値表現を在庫整数へ正規化する。"""
    try:
        return int(float(str(value).replace(",", "").replace("¥", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def _is_valid_inventory_number(value) -> bool:
    """空欄または整数として扱える有限値だけを在庫値として許可する。"""
    if value is None or str(value).strip() == "":
        return True
    try:
        number = float(str(value).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number.is_integer()


def inspect_live_row_issues(
    sheet_rows: Sequence[Sequence[object]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A:GのSKU重複とF/Gの非数値を返す。対象SKUは更新禁止にする。"""
    seen: set[str] = set()
    duplicates: set[str] = set()
    invalid: set[str] = set()
    for row in sheet_rows:
        sku = str(row[0]).strip() if row else ""
        if not sku:
            continue
        if sku in seen:
            duplicates.add(sku)
        seen.add(sku)
        f_value = row[5] if len(row) > 5 else ""
        g_value = row[6] if len(row) > 6 else ""
        if not _is_valid_inventory_number(f_value) or not _is_valid_inventory_number(g_value):
            invalid.add(sku)
    return tuple(sorted(duplicates)), tuple(sorted(invalid))


@dataclass(frozen=True)
class LiveInventoryRow:
    row_index: int
    sku: str
    f_value: int
    g_value: int


@dataclass(frozen=True)
class StocktakeChange:
    row_index: int
    sku: str
    input_value: int
    f_before: int
    g_before: int
    f_after: int
    g_after: int
    mode: str


@dataclass(frozen=True)
class StocktakePlan:
    changes: tuple[StocktakeChange, ...]
    missing: tuple[str, ...]
    conflicts: tuple[str, ...]
    unchanged: tuple[str, ...]


def index_live_rows(
    sheet_rows: Sequence[Sequence[object]], start_row: int = 7
) -> dict[str, LiveInventoryRow]:
    """A:G の行を SKU で索引化する（重複時は従来どおり先頭行）。"""
    indexed: dict[str, LiveInventoryRow] = {}
    for row_index, row in enumerate(sheet_rows, start=start_row):
        sku = str(row[0]).strip() if row else ""
        if not sku or sku in indexed:
            continue
        indexed[sku] = LiveInventoryRow(
            row_index=row_index,
            sku=sku,
            f_value=as_int(row[5]) if len(row) > 5 else 0,
            g_value=as_int(row[6]) if len(row) > 6 else 0,
        )
    return indexed


def plan_stocktake_updates(
    entries: Iterable[tuple[str, int]],
    displayed_g: Mapping[str, object],
    live_rows: Mapping[str, LiveInventoryRow],
    *,
    add_mode: bool,
    blocked_skus: Iterable[str] = (),
) -> StocktakePlan:
    """ライブ F/G から更新を計画し、表示後に変わった G を競合扱いにする。"""
    changes: list[StocktakeChange] = []
    missing: list[str] = []
    conflicts: list[str] = []
    unchanged: list[str] = []
    mode = "加算" if add_mode else "置換"
    blocked = set(blocked_skus)

    for sku, raw_input in entries:
        if sku in blocked:
            conflicts.append(sku)
            continue
        live = live_rows.get(sku)
        if live is None:
            missing.append(sku)
            continue
        if live.g_value != as_int(displayed_g.get(sku)):
            conflicts.append(sku)
            continue

        input_value = as_int(raw_input)
        f_after = live.f_value + input_value if add_mode else input_value
        if f_after == live.f_value:
            unchanged.append(sku)
            continue
        # F = G + その他増減。送信時のライブ F/G の差分だけ G に加える。
        g_after = live.g_value + (f_after - live.f_value)
        changes.append(
            StocktakeChange(
                row_index=live.row_index,
                sku=sku,
                input_value=input_value,
                f_before=live.f_value,
                g_before=live.g_value,
                f_after=f_after,
                g_after=g_after,
                mode=mode,
            )
        )

    return StocktakePlan(
        changes=tuple(changes),
        missing=tuple(missing),
        conflicts=tuple(conflicts),
        unchanged=tuple(unchanged),
    )


def find_verification_mismatches(
    changes: Iterable[StocktakeChange],
    live_rows: Mapping[str, LiveInventoryRow],
    *,
    blocked_skus: Iterable[str] = (),
) -> tuple[str, ...]:
    """書込後の F/G が計画値と一致しない SKU を返す。"""
    mismatches = []
    blocked = set(blocked_skus)
    for change in changes:
        actual = live_rows.get(change.sku)
        if (
            change.sku in blocked
            or actual is None
            or actual.f_value != change.f_after
            or actual.g_value != change.g_after
        ):
            mismatches.append(change.sku)
    return tuple(mismatches)


def find_prewrite_drift(
    changes: Iterable[StocktakeChange],
    live_rows: Mapping[str, LiveInventoryRow],
    *,
    blocked_skus: Iterable[str] = (),
) -> tuple[str, ...]:
    """予約取得後に行位置または変更前F/Gが動いたSKUを返す。

    別端末が先に完了すると、その予約は既に終端扱いになってロック対象外となる。
    その場合でも、予約前に作った古い計画で上書きしないための最終CAS相当チェック。
    """
    drifted = []
    blocked = set(blocked_skus)
    for change in changes:
        actual = live_rows.get(change.sku)
        if (
            change.sku in blocked
            or actual is None
            or actual.row_index != change.row_index
            or actual.f_value != change.f_before
            or actual.g_value != change.g_before
        ):
            drifted.append(change.sku)
    return tuple(drifted)


def find_reservation_conflicts(
    log_rows: Sequence[Sequence[object]],
    current_batch_id: str,
    target_skus: Iterable[str],
    *,
    now: datetime,
    ttl_seconds: int = 300,
) -> tuple[str, ...]:
    """08ログ末尾から、同時棚卸で先に予約されたSKUを検出する。

    Google Sheets の append は行順が確定するため、同じSKUを同時に予約しても
    最初の有効予約だけを勝者にできる。完了・失敗行があるバッチと期限切れ予約は
    ロックとして扱わない。
    """
    terminal_batches: set[str] = set()
    parsed: list[tuple[str, str, str, str, datetime | None]] = []
    for row in log_rows:
        values = list(row) + [""] * (8 - len(row))
        process = str(values[1]).strip()
        sku = str(values[2]).strip()
        event_id = str(values[5]).strip()
        status = str(values[6]).strip()
        batch_id = event_id.rsplit(":", 1)[0] if ":" in event_id else event_id
        timestamp = None
        try:
            timestamp = datetime.strptime(str(values[0]).strip(), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            pass
        parsed.append((process, sku, batch_id, status, timestamp))
        if process == "モバイル棚卸" and status != "予約中" and batch_id:
            terminal_batches.add(batch_id)

    cutoff = now - timedelta(seconds=ttl_seconds)
    winner_by_sku: dict[str, str] = {}
    for process, sku, batch_id, status, timestamp in parsed:
        if (
            process != "モバイル棚卸予約"
            or status != "予約中"
            or not sku
            or not batch_id
            or batch_id in terminal_batches
            or timestamp is None
            or timestamp < cutoff
            or timestamp > now + timedelta(seconds=60)
        ):
            continue
        winner_by_sku.setdefault(sku, batch_id)

    conflicts = [
        sku for sku in target_skus
        if winner_by_sku.get(sku) not in (None, current_batch_id)
    ]
    return tuple(dict.fromkeys(conflicts))
