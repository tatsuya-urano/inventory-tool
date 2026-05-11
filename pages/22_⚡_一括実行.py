"""
⚡ 一括実行（朝バッチ相当）

朝バッチ(morning_batch.py)をボタン1発で起動する。
通常は Task Scheduler で 07:30 に自動実行されるが、
- 別PCで手動実行したい
- 失敗後に再実行したい
- 売上補完だけ走らせたい
等の時にこのページから実行する。
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="一括実行", page_icon="⚡", layout="wide")
st.title("⚡ 一括実行（朝バッチ相当）")
st.caption("morning_batch.py をここから起動できます")
ui.sidebar_common()

# ============================================================
# パス
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 07_Streamlitアプリ/pages/22_*.py → 統合プロジェクト/
BATCH_DIR = PROJECT_ROOT / "08_自動実行"
BATCH_SCRIPT = BATCH_DIR / "morning_batch.py"
LOG_DIR = BATCH_DIR / "logs"

# ============================================================
# 朝バッチ起動セクション
# ============================================================
st.markdown("## 🌅 朝バッチ実行")

st.info(
    "通常は毎朝 07:30 に Task Scheduler が自動実行します。\n"
    "このボタンは手動再実行用です（別PC作業時 / 失敗時の再実行）。"
)

with st.expander("⚙ オプション", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        opt_no_line = st.checkbox("LINE通知をスキップ (--no-line)", value=False)
        opt_skip_amazon = st.checkbox("Amazon売上取得をスキップ (--skip-amazon-fetch)", value=False)
        opt_skip_rakuten = st.checkbox("楽天売上取得をスキップ (--skip-rakuten-fetch)", value=False)
        opt_skip_monthly = st.checkbox("月次リセットをスキップ (--skip-monthly-reset)", value=True,
                                       help="月初(1日)以外は実質スキップ。同日2回目はOFFでも自動スキップされる")
    with c2:
        opt_skip_recommend = st.checkbox("推奨発注をスキップ (--skip-recommend)", value=False)
        opt_skip_fba = st.checkbox("FBA補充をスキップ (--skip-fba)", value=False)
        opt_skip_repair = st.checkbox("売上補完をスキップ (--skip-sales-repair)", value=False)
        opt_rakuten_days = st.number_input("楽天取得を遡る日数", min_value=1, max_value=30, value=7,
                                            help="過去N日分を再取得。重複は自動スキップ")

    opt_limit = st.number_input("月間発注上限 (円)", min_value=0, value=1_000_000, step=100_000)

go = st.button("🌅 朝バッチを今すぐ実行", type="primary", use_container_width=True)

if go:
    if not BATCH_SCRIPT.exists():
        st.error(f"morning_batch.py が見つかりません: {BATCH_SCRIPT}")
        st.stop()

    cmd = [sys.executable, str(BATCH_SCRIPT), "--limit", str(int(opt_limit))]
    if opt_no_line:
        cmd.append("--no-line")
    if opt_skip_amazon:
        cmd.append("--skip-amazon-fetch")
    if opt_skip_rakuten:
        cmd.append("--skip-rakuten-fetch")
    if opt_skip_monthly:
        cmd.append("--skip-monthly-reset")
    if opt_skip_recommend:
        cmd.append("--skip-recommend")
    if opt_skip_fba:
        cmd.append("--skip-fba")
    if opt_skip_repair:
        cmd.append("--skip-sales-repair")
    cmd += ["--rakuten-days", str(int(opt_rakuten_days))]

    st.code("> " + " ".join(cmd), language="text")
    started = datetime.now()
    log_box = st.empty()
    status = st.empty()
    status.info(f"⏳ 実行中... ({started:%H:%M:%S} 開始)")

    # Windows の cp932 で絵文字が落ちないよう、子プロセスのIO encodingをUTF-8に強制
    import os
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BATCH_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_env,
        )

        # DOM更新の頻度を抑えるため、数行たまるたびに描画
        lines: list[str] = []
        last_render = 0
        for i, line in enumerate(proc.stdout):  # type: ignore[union-attr]
            lines.append(line.rstrip())
            if i - last_render >= 5 or len(lines) <= 10:
                log_box.code("\n".join(lines[-200:]), language="text")
                last_render = i
        # 最終描画
        log_box.code("\n".join(lines[-200:]), language="text")

        rc = proc.wait()
        elapsed = (datetime.now() - started).total_seconds()
        if rc == 0:
            status.success(f"✅ 完了 (rc=0, {elapsed:.0f}秒)")
            st.balloons()
        else:
            status.error(f"❌ 異常終了 (rc={rc}, {elapsed:.0f}秒) — ログを確認してください")
    except Exception as e:
        status.error(f"❌ 起動失敗: {e}")

st.markdown("---")

# ============================================================
# 直近ログ
# ============================================================
st.markdown("## 📜 直近のバッチログ")

if LOG_DIR.exists():
    today_log = LOG_DIR / f"morning_batch_{datetime.now():%Y%m%d}.log"
    if today_log.exists():
        st.caption(f"今日のログ: {today_log.name} ({today_log.stat().st_size:,} bytes)")
        try:
            txt = today_log.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join(txt.splitlines()[-100:])
            st.code(tail or "(空)", language="text")
        except Exception as e:
            st.warning(f"ログ読込失敗: {e}")
    else:
        st.caption(f"今日({today_log.name})のログはまだありません")

    with st.expander("過去のログ一覧", expanded=False):
        logs = sorted(LOG_DIR.glob("morning_batch_*.log"), reverse=True)[:20]
        for p in logs:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            st.write(f"- `{p.name}` — {mtime:%Y-%m-%d %H:%M} / {p.stat().st_size:,} bytes")
else:
    st.caption(f"ログディレクトリがありません: {LOG_DIR}")

st.markdown("### 📋 個別ページへのリンク")
st.markdown(
    """
- 🛒 [推奨発注リスト](/推奨発注リスト) — リスト再生成 + CSV出力 + スプシ書き戻し
- 📦 [FBA補充プラン](/FBA補充プラン) — 補充計算 + 確定数編集 + スプシ書き戻し
- 📤 [在庫PUSH](/在庫PUSH) — 楽天/Amazon に在庫を反映
- 📈 [月次サマリ](/月次サマリ) — 月×チャネル別売上集計
- 📊 [大分類別販売集計](/大分類別販売集計) — カテゴリ別月推移
"""
)
