"""
ユーザー設定の永続化（再起動しても保持）

`.streamlit/user_prefs.json` に保存。各ページが個別キーで読み書き。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "user_prefs.json"


def _load_all() -> dict[str, Any]:
    if not PREFS_PATH.exists():
        return {}
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(prefs: dict[str, Any]) -> None:
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_pref(key: str, default: Any = None) -> Any:
    """指定キーの値を取得"""
    return _load_all().get(key, default)


def set_pref(key: str, value: Any) -> None:
    """指定キーに値を保存"""
    prefs = _load_all()
    prefs[key] = value
    _save_all(prefs)


def del_pref(key: str) -> None:
    prefs = _load_all()
    prefs.pop(key, None)
    _save_all(prefs)
