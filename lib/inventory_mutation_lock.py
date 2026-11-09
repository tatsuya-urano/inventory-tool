"""Google Sheetsを使った全在庫更新経路共通の排他ロック。

公開モバイル棚卸も統合アプリ・月締めと同じ ``__在庫更新ロック`` を使う。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
import socket
import time
from typing import Any, Iterator, Sequence
import uuid

try:
    from gspread.exceptions import WorksheetNotFound
except ImportError:  # pragma: no cover
    class WorksheetNotFound(Exception):
        pass


SHEET_NAME = "__在庫更新ロック"
HEADERS = ("owner", "purpose", "status", "created_at", "expires_at", "released_at", "host", "note")
ACTIVE = "ACTIVE"
RELEASED = "RELEASED"
DEFAULT_TTL_SECONDS = 7200
TRANSIENT_RETRY_DELAYS = (1, 2, 4, 8, 15)
LOCK_READ_TAIL_ROWS = 5000


class InventoryMutationLockError(RuntimeError):
    pass


class InventoryMutationLockBusy(InventoryMutationLockError):
    def __init__(self, *, owner: str, purpose: str, expires_at: str) -> None:
        self.owner, self.purpose, self.expires_at = owner, purpose, expires_at
        super().__init__(f"別の在庫更新が実行中です (purpose={purpose or '不明'}, owner={owner or '不明'}, expires_at={expires_at or '不明'})")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _row_values(row: Sequence[object]) -> list[str]:
    values = [str(value or "") for value in row[:len(HEADERS)]]
    return values + [""] * (len(HEADERS) - len(values))


def _is_retryable_error(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    text = str(exc).lower()
    if status in {429, 500, 502, 503, 504}:
        return True
    return any(marker in text for marker in (
        "quota exceeded", "429", "internal server error", "bad gateway",
        "service unavailable", "gateway timeout", "connection reset",
        "connection aborted", "timed out", "timeout", "temporarily unavailable",
    ))


def _with_retry(operation):
    for attempt in range(len(TRANSIENT_RETRY_DELAYS) + 1):
        try:
            return operation()
        except Exception as exc:
            if not _is_retryable_error(exc) or attempt >= len(TRANSIENT_RETRY_DELAYS):
                raise
            time.sleep(TRANSIENT_RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")


def _read_rows(ws: Any) -> list[list[str]]:
    try:
        if hasattr(ws, "batch_get") and hasattr(ws, "row_count"):
            last_row = max(2, int(getattr(ws, "row_count", 2) or 2))
            tail_start = max(2, last_row - LOCK_READ_TAIL_ROWS + 1)
            blocks = _with_retry(lambda: ws.batch_get(
                ["A1:H1", f"A{tail_start}:H"],
                value_render_option="UNFORMATTED_VALUE",
            ))
            header = blocks[0][0] if blocks and blocks[0] else []
            tail = blocks[1] if len(blocks) > 1 else []
            rows = [header] + ([[]] * (tail_start - 2)) + list(tail)
        else:
            rows = _with_retry(ws.get_all_values)
        return [_row_values(row) for row in rows]
    except Exception as exc:
        raise InventoryMutationLockError("共有在庫ロックを再読込できないため、在庫更新を中止します") from exc


def _append_row_number(response: object) -> int | None:
    if not isinstance(response, dict):
        return None
    updated_range = str(response.get("updates", {}).get("updatedRange", ""))
    match = re.search(r"!A(\d+):H\d+$", updated_range)
    return int(match.group(1)) if match else None


def _update_row(ws: Any, row_number: int, values: Sequence[object]) -> None:
    try:
        _with_retry(lambda: ws.update(range_name=f"A{row_number}:H{row_number}", values=[[str(value or "") for value in values]], value_input_option="RAW"))
    except Exception as exc:
        raise InventoryMutationLockError(f"共有在庫ロック行{row_number}を更新できません") from exc


def _write_header(ws: Any) -> None:
    _update_row(ws, 1, HEADERS)
    rows = _read_rows(ws)
    if not rows or tuple(rows[0]) != HEADERS:
        raise InventoryMutationLockError("共有在庫ロックのヘッダーを確認できないため、在庫更新を中止します")


def _ensure_worksheet(spreadsheet: Any) -> Any:
    created = False
    try:
        ws = _with_retry(lambda: spreadsheet.worksheet(SHEET_NAME))
    except WorksheetNotFound:
        try:
            ws = _with_retry(lambda: spreadsheet.add_worksheet(title=SHEET_NAME, rows=2000, cols=len(HEADERS)))
            created = True
        except Exception:
            try:
                ws = _with_retry(lambda: spreadsheet.worksheet(SHEET_NAME))
            except Exception as read_exc:
                raise InventoryMutationLockError("共有在庫ロック用シートを作成・取得できません") from read_exc
    except Exception as exc:
        raise InventoryMutationLockError("共有在庫ロック用シートを取得できません") from exc
    rows = _read_rows(ws)
    if not rows or not any(rows[0]):
        _write_header(ws)
    elif tuple(rows[0]) != HEADERS:
        raise InventoryMutationLockError(f"{SHEET_NAME} の列構成が不正なため、在庫更新を中止します")
    if created:
        try:
            ws.hide()
        except Exception as exc:
            raise InventoryMutationLockError("共有在庫ロック用シートを非表示にできません") from exc
    return ws


def _record(values: Sequence[object], row_number: int) -> dict[str, str | int]:
    record: dict[str, str | int] = dict(zip(HEADERS, _row_values(values)))
    record["_row"] = row_number
    return record


def _is_live_active(record: dict[str, str | int], now: datetime) -> bool:
    if record.get("status") != ACTIVE:
        return False
    expires_at = _parse_time(record.get("expires_at"))
    return expires_at is None or expires_at > now


def _release_values(record: dict[str, str | int], *, released_at: datetime, note: str) -> list[str]:
    return [str(record.get("owner", "")), str(record.get("purpose", "")), RELEASED, str(record.get("created_at", "")), str(record.get("expires_at", "")), _iso(released_at), str(record.get("host", "")), note]


@dataclass
class InventoryMutationLock:
    worksheet: Any
    owner: str
    purpose: str
    row_number: int
    created_at: datetime
    expires_at: datetime
    host: str
    _released: bool = False

    def release(self, *, note: str = "") -> None:
        if self._released:
            return
        rows = _read_rows(self.worksheet)
        own_rows = [_record(row, index) for index, row in enumerate(rows[1:], start=2) if row[0] == self.owner]
        if len(own_rows) != 1:
            raise InventoryMutationLockError("共有在庫ロックの自分の行を一意に確認できません")
        own = own_rows[0]
        _update_row(self.worksheet, int(own["_row"]), _release_values(own, released_at=_utc_now(), note=note))
        self._released = True


def acquire_inventory_mutation_lock(spreadsheet: Any, *, purpose: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, owner: str | None = None, now: datetime | None = None) -> InventoryMutationLock:
    purpose = str(purpose or "").strip()
    if not purpose:
        raise ValueError("purpose は必須です")
    if int(ttl_seconds) <= 0:
        raise ValueError("ttl_seconds は1以上で指定してください")
    acquired_at = _as_utc(now or _utc_now())
    expires_at = acquired_at + timedelta(seconds=int(ttl_seconds))
    lock_owner = str(owner or "").strip() or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
    host = socket.gethostname()
    ws = _ensure_worksheet(spreadsheet)
    try:
        appended = [lock_owner, purpose, ACTIVE, _iso(acquired_at), _iso(expires_at), "", host, ""]
        append_response = _with_retry(lambda: ws.append_row(appended, value_input_option="RAW"))
    except Exception as exc:
        raise InventoryMutationLockError("共有在庫ロックを予約できないため、在庫更新を中止します") from exc
    appended_row = _append_row_number(append_response)
    try:
        rows = _read_rows(ws)
    except InventoryMutationLockError:
        if appended_row is not None:
            try:
                _update_row(ws, appended_row, [*appended[:2], RELEASED, *appended[3:5], _iso(_utc_now()), host, "予約後の確認読込失敗を自動解除"])
            except InventoryMutationLockError:
                pass
        raise
    records = [_record(row, index) for index, row in enumerate(rows[1:], start=2)]
    own_rows = [record for record in records if record.get("owner") == lock_owner]
    if len(own_rows) != 1 or own_rows[0].get("status") != ACTIVE:
        raise InventoryMutationLockError("追記した共有在庫ロックを一意に確認できないため、在庫更新を中止します")
    own = own_rows[0]
    live = [record for record in records if _is_live_active(record, acquired_at)]
    if not live:
        raise InventoryMutationLockError("有効な共有在庫ロックを確認できないため、在庫更新を中止します")
    winner = min(live, key=lambda record: int(record["_row"]))
    if winner.get("owner") != lock_owner:
        try:
            _update_row(ws, int(own["_row"]), _release_values(own, released_at=acquired_at, note="別処理が先に共有ロックを取得"))
        except InventoryMutationLockError:
            pass
        raise InventoryMutationLockBusy(owner=str(winner.get("owner", "")), purpose=str(winner.get("purpose", "")), expires_at=str(winner.get("expires_at", "")))
    return InventoryMutationLock(ws, lock_owner, purpose, int(own["_row"]), acquired_at, expires_at, host)


@contextmanager
def inventory_mutation_lock(spreadsheet: Any, *, purpose: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, owner: str | None = None) -> Iterator[InventoryMutationLock]:
    lock = acquire_inventory_mutation_lock(spreadsheet, purpose=purpose, ttl_seconds=ttl_seconds, owner=owner)
    try:
        yield lock
    except BaseException:
        try:
            lock.release(note="処理中断")
        except InventoryMutationLockError:
            pass
        raise
    else:
        lock.release(note="正常終了")
