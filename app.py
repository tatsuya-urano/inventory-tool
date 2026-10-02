"""📱 モバイル棚卸 — 単機能アプリ (これ1画面だけ)

このデプロイアプリは「棚卸」専用。小分類順にSKUの実カウント数を入力 → 04の
G列(月初在庫)を逆算して 自社倉庫(F) が実カウントと一致するよう反映する。

他の分析ページ(売上集計・月次サマリ等)は Streamlit Cloud 無料枠の
メモリ超過(Oh no.)の原因になるため撤去し、家PC/事務所のフル版に集約した。

逆算ロジック(列移設に強い):
  F = G + (I - J - 当月売上 - Z - S)  ← G以外はGに依存しない
  よって G_new = G_old + (実カウント - 現在のF) とすれば F_new = 実カウント。
"""
from datetime import datetime
import time
import uuid

import streamlit as st
import pandas as pd

from lib import sheets
from lib import inventory_mutation_lock
from lib.mobile_stocktake import (
    find_prewrite_drift,
    find_reservation_conflicts,
    find_verification_mismatches,
    index_live_rows,
    inspect_live_row_issues,
    plan_stocktake_updates,
)

st.set_page_config(page_title="モバイル棚卸", page_icon="📱", layout="centered")

st.markdown("""
<style>
    .stButton>button {
        height: 52px !important;
        font-size: 18px !important;
        font-weight: 700 !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 18px !important;
        height: 46px !important;
    }
    /* 反映(送信)ボタンを画面左下に常駐させる。
       右下はStreamlit CloudのManage appボタンと重なるため左下に配置 */
    div[data-testid="stFormSubmitButton"] {
        position: fixed;
        bottom: 24px;
        left: 16px;
        z-index: 9999;
        width: auto !important;
    }
    div[data-testid="stFormSubmitButton"] button {
        height: 52px !important;
        font-size: 17px !important;
        font-weight: 700 !important;
        border-radius: 28px !important;
        padding: 0 22px !important;
        box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    }
</style>
""", unsafe_allow_html=True)

st.title("📱 モバイル棚卸")
st.caption("小分類順に実在庫を入力 → 自社倉庫に反映")

# 最新化(軽量)。フル版のような全シートナビは撤去し、必要な再読込だけ残す。
if st.button("🔄 データを最新化", help="在庫スナップを取り直します"):
    # セッション内の反映済み値も捨てる。これを残すとスナップを最新化しても
    # 古い手元値が優先され、別PCの変更を画面に出せない。
    st.session_state.pop("mob_applied", None)
    st.cache_data.clear()
    sheets._invalidate_one("04_在庫管理")
    sheets._invalidate_one("04_在庫スナップ")
    st.rerun()


def _f(v):
    try:
        return int(float(str(v).replace(",", "").replace("¥", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _read_live_inventory(ws, last_row: int):
    """04_在庫管理 A:G をキャッシュを通さずライブ取得する。"""
    rows = ws.get(
        f"A7:G{last_row}",
        value_render_option="UNFORMATTED_VALUE",
    )
    duplicates, invalid = inspect_live_row_issues(rows)
    return index_live_rows(rows, start_row=7), duplicates, invalid


def _reserve_stocktake(log_ws, changes, batch_id: str, now: datetime):
    """共有ログに予約をappendし、同じSKUの最初の予約だけを通す。"""
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        [
            timestamp,
            "モバイル棚卸予約",
            change.sku,
            f"変更前F:{change.f_before} G:{change.g_before}",
            f"予定F:{change.f_after} G:{change.g_after}",
            f"{batch_id}:{seq:03d}",
            "予約中",
            "5分で自動失効",
        ]
        for seq, change in enumerate(changes, start=1)
    ]
    log_ws.append_rows(rows, value_input_option="USER_ENTERED")
    # row_count は空の予約行を含むグリッド総数なので、実際の最終ログ行を使う。
    last_row = max(len(log_ws.col_values(1)), 2)
    recent = log_ws.get(
        f"A{max(2, last_row - 5000)}:H{last_row}",
        value_render_option="FORMATTED_VALUE",
    )
    return find_reservation_conflicts(
        recent,
        batch_id,
        [change.sku for change in changes],
        now=now,
    )


# 04_在庫管理はTODAY()依存の重い数式で読込に8分半かかる。表示用は家PCバッチが焼く
# 数式ゼロの軽量スナップ(0.4秒)を読む(小分類/販売チャネルもスナップ列に同梱)。
# スナップ未生成時のみ、重い04直読み+マスタにフォールバック。
with st.spinner("読込中..."):
    try:
        inv_df = sheets.load_inventory_snapshot()
    except Exception:
        inv_df = pd.DataFrame()
    from_snapshot = not inv_df.empty
    if not from_snapshot:
        st.info("⏳ 在庫スナップ未生成のため04を直読みします（数分かかることがあります）")
        try:
            inv_df = sheets.load_inventory()
        except Exception as e:
            st.error("📡 在庫データの取得に失敗しました（サーバー混雑かも）。")
            st.caption(f"詳細: {type(e).__name__}")
            if st.button("🔄 もう一度読み込む"):
                sheets._invalidate_one("04_在庫管理")
                st.rerun()
            st.stop()
        # フォールバック時のみ小分類/チャネルをマスタから補う
        try:
            master_df = sheets.load_master()
        except Exception:
            master_df = pd.DataFrame()
            st.warning("⚠ 小分類を取得できませんでした（サーバー混雑）。並びは小分類なしになります。")

if inv_df.empty:
    st.error("在庫データ読込失敗")
    st.stop()

code_col = inv_df.columns[0]
title_col = inv_df.columns[1] if len(inv_df.columns) > 1 else code_col

# フォールバック(重い04直読)時: 商品コード→小分類(マスタE=idx4)/販売チャネル(F=idx5)
small_map = {}
channel_map = {}
if not from_snapshot:
    if not master_df.empty and len(master_df.columns) > 4:
        for c, s in zip(master_df.iloc[:, 0].astype(str).str.strip(),
                        master_df.iloc[:, 4].astype(str)):
            if c:
                small_map[c] = s.strip()
    if not master_df.empty and len(master_df.columns) > 5:
        for c, ch in zip(master_df.iloc[:, 0].astype(str).str.strip(),
                         master_df.iloc[:, 5].astype(str)):
            if c:
                channel_map[c] = ch.strip()

# 在庫行 → 作業用テーブル
#  - Amazon専売(AMA専売) は自社倉庫に無いので除外
#  - 小分類なし(マスタ未登録)は終売とみなし除外。ただし小分類が全く取れない時は
#    全行が小分類なし扱いになり全滅するため、その時は除外しない
# 自分がこのセッションで反映した値を覚えておく {sku: (F, G)}。
# F列はARRAYFORMULA(計算値)で、Gを書いた直後の再読込では古い値が返ることがあり、
# それを基準にすると2回目の反映が「変化なし」とスキップされてしまう。
# そこで自分の反映済み値があればそれを現在値として使う。
applied = st.session_state.setdefault("mob_applied", {})

if from_snapshot:
    have_small = ("小分類" in inv_df.columns
                  and inv_df["小分類"].astype(str).str.strip().ne("").any())
else:
    have_small = bool(small_map)

rows = []
for _, r in inv_df.iterrows():
    code = str(r[code_col]).strip()
    if not code:
        continue
    if from_snapshot:
        channel = str(r.get("販売チャネル", "")).strip()
        small = str(r.get("小分類", "")).strip()
        f_sheet = _f(r.get("自社倉庫", 0))   # 自社倉庫(スナップ焼付値)
        g_sheet = _f(r.get("月初在庫", 0))   # 月初在庫(スナップ焼付値)
    else:
        channel = channel_map.get(code, "")
        small = small_map.get(code, "")
        f_sheet = _f(r.iloc[5]) if len(r) > 5 else 0   # F 自社倉庫(計算値)
        g_sheet = _f(r.iloc[6]) if len(r) > 6 else 0   # G 月初在庫(直接値)
    if channel == "AMA専売":
        continue
    if have_small and not small:
        continue  # 小分類なし=終売とみなし非表示
    f_cur, g_cur = applied.get(code, (f_sheet, g_sheet))
    rows.append({
        "小分類": small,
        "SKU": code,
        "_G": g_cur,
        "現在庫": f_cur,
    })
work = pd.DataFrame(rows)

# 04_在庫管理 / 04_在庫スナップに同一SKUが複数行あると、同じlabelの
# number_inputが複数生成されてStreamlitDuplicateElementIdになる。
# 書込み側も同一SKUの先頭行を更新対象としているため、表示も先頭行へ統一する。
duplicate_skus = (
    work.loc[work["SKU"].duplicated(keep=False), "SKU"]
    .drop_duplicates()
    .tolist()
)
if duplicate_skus:
    work = work.drop_duplicates(subset=["SKU"], keep="first").reset_index(drop=True)
    examples = "、".join(duplicate_skus[:5])
    suffix = "…" if len(duplicate_skus) > 5 else ""
    st.warning(
        f"⚠ 在庫データに重複SKUが{len(duplicate_skus)}件あります。"
        f"画面では先頭行だけ表示します: {examples}{suffix}"
    )

# 絞り込み（小分類・SKUとも文字入力で検索）
sc1, sc2 = st.columns(2)
small_kw = sc1.text_input("🔍 小分類検索", "", key="mob_count_small_kw",
                          placeholder="小分類の一部")
kw = sc2.text_input("🔍 SKU検索", "", key="mob_count_kw", placeholder="SKUの一部")

view = work.copy()
if small_kw.strip():
    view = view[view["小分類"].str.contains(small_kw, case=False, na=False)]
if kw.strip():
    view = view[view["SKU"].str.contains(kw, case=False, na=False)]

# 小分類 昇順 → SKU 昇順(上る順)
view = view.sort_values(["小分類", "SKU"], ascending=[True, True]).reset_index(drop=True)

if view.empty:
    st.warning("該当SKUなし")
    st.stop()

# data_editorはスマホで数値が累積・消せない不具合があるため、st.formの
# 行ごとnumber_inputに変更。formは送信ボタンを押すまで再実行しないので、
# 入力途中で数字が勝手に足される/消せない問題が起きない。
# 件数が多いと重いので200件ずつページ送り。ページ内で入力→反映を繰り返す。
PAGE_SIZE = 200
total = len(view)
n_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
if n_pages > 1:
    page = st.selectbox(
        "ページ (200件ずつ)",
        list(range(1, n_pages + 1)),
        format_func=lambda p: f"{p}/{n_pages}ページ "
                              f"({(p-1)*PAGE_SIZE+1}〜{min(p*PAGE_SIZE, total)}件)",
        key="mob_count_page",
    )
else:
    page = 1
start = (page - 1) * PAGE_SIZE
view_page = view.iloc[start:start + PAGE_SIZE].reset_index(drop=True)

# 入力方法。棚→バッファのように2回に分けて数える時は「加算」を使う
mode = st.radio(
    "入力方法",
    ["置き換え（数えた実数）", "加算（今の在庫に足す）"],
    horizontal=True,
    key="mob_count_mode",
    help="棚を先に数えて反映 → 次にバッファを数える時は『加算』にすると、"
         "入力した数が今の在庫に足されます",
)
add_mode = mode.startswith("加算")

if add_mode:
    st.caption(f"全{total}件中 {start+1}〜{min(start+PAGE_SIZE, total)}件目　"
               "🟢加算モード：入力した数を今の在庫に足します(空欄・0はスキップ)。"
               "ページを変える前に反映を押してください")
else:
    st.caption(f"全{total}件中 {start+1}〜{min(start+PAGE_SIZE, total)}件目　"
               "置き換えモード：入力した実数に在庫を合わせます(空欄はスキップ)。"
               "ページを変える前に反映を押してください")

gmap = dict(zip(view_page["SKU"], view_page["_G"]))

# clear_on_submit=True: 反映するたびに入力欄を空にする。
# (Falseだと前回の数字が残り、もう一度押すと再適用=加算モードで二重に足される)
# ※clear_on_submit時は number_input に key を付けてはいけない。
#   key付きだと送信時に session_state クリアと戻り値取得が競合し、
#   再入力した値が None 扱いになって反映されない。戻り値だけで受け取る。
inputs = {}
with st.form("mob_count_form", clear_on_submit=True):
    for _, row in view_page.iterrows():
        sku = row["SKU"]
        f_old = int(row["現在庫"])
        small = row["小分類"] or "（小分類なし）"
        label = (f"{small}　|　{sku}　(現在 {f_old}) ＋足す数"
                 if add_mode else f"{small}　|　{sku}　(現在 {f_old})")
        inputs[sku] = st.number_input(
            label,
            min_value=0, step=1, value=None,
        )
    submitted = st.form_submit_button(
        "💾 反映", type="primary", use_container_width=False)

if submitted:
    # 画面を開いた後に売上・月次繰越・別PCの棚卸が動く可能性があるため、
    # ここでは入力値だけを回収する。逆算は必ず送信時のライブ F/G で行う。
    entries = []
    for sku in view_page["SKU"]:
        newc = inputs.get(sku)
        if newc is None:
            continue
        newc = int(newc)
        if add_mode and newc == 0:
            continue
        entries.append((sku, newc))

    if not entries:
        st.info("入力された変更がありません(空欄・置換で同値・加算で0のみ)")
    else:
        global_inventory_lock = None
        try:
            ss = sheets.get_spreadsheet()
            # 月締め・入荷・FBA移動・別端末棚卸と同じ共有ロックを使う。
            # 取得できない場合はライブ値を読む前に停止し、古い差分を作らない。
            global_inventory_lock = (
                inventory_mutation_lock.acquire_inventory_mutation_lock(
                    ss, purpose="公開モバイル棚卸", ttl_seconds=600,
                )
            )
            ws = ss.worksheet("04_在庫管理")
            codes = ws.col_values(1)
            last_row = max(len(codes), 7)
            live_before, duplicate_skus, invalid_skus = _read_live_inventory(ws, last_row)
            plan = plan_stocktake_updates(
                entries,
                gmap,
                live_before,
                add_mode=add_mode,
                blocked_skus=set(duplicate_skus) | set(invalid_skus),
            )

            # 1件でも G が表示時から変わっていたら全件停止する。
            # 一部だけ書くと、利用者がどこまで反映されたか判断できず再入力で重複する。
            if plan.conflicts or plan.missing:
                details = []
                duplicate_targets = [
                    sku for sku in plan.conflicts if sku in set(duplicate_skus)
                ]
                invalid_targets = [
                    sku for sku in plan.conflicts if sku in set(invalid_skus)
                ]
                ordinary_conflicts = [
                    sku for sku in plan.conflicts
                    if sku not in set(duplicate_skus) and sku not in set(invalid_skus)
                ]
                if duplicate_targets:
                    details.append(
                        "SKU重複 " + "、".join(duplicate_targets[:10])
                        + ("…" if len(duplicate_targets) > 10 else "")
                    )
                if invalid_targets:
                    details.append(
                        "F/G数式・数値エラー " + "、".join(invalid_targets[:10])
                        + ("…" if len(invalid_targets) > 10 else "")
                    )
                if ordinary_conflicts:
                    details.append(
                        "表示後のG変更 " + "、".join(ordinary_conflicts[:10])
                        + ("…" if len(ordinary_conflicts) > 10 else "")
                    )
                if plan.missing:
                    details.append(
                        "未登録 " + "、".join(plan.missing[:10])
                        + ("…" if len(plan.missing) > 10 else "")
                    )
                st.error(
                    "安全確認を通過しなかったため全件の反映を停止しました。"
                    "表示後の変更は『データを最新化』後に再入力し、重複や数式エラーは"
                    "在庫管理シートを修正してください。\n\n"
                    + " / ".join(details)
                )
            elif not plan.changes:
                st.info("送信時の最新在庫と同じため、変更はありません")
            else:
                batch_id = (
                    "MOB-"
                    + datetime.now().strftime("%Y%m%d%H%M%S")
                    + "-"
                    + uuid.uuid4().hex[:12]
                )
                log_ws = ss.worksheet("08_ログ履歴")
                reservation_conflicts = _reserve_stocktake(
                    log_ws, plan.changes, batch_id, datetime.now()
                )
                if reservation_conflicts:
                    stop_rows = [
                        [
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "モバイル棚卸",
                            change.sku,
                            "",
                            "",
                            f"{batch_id}:{seq:03d}",
                            "競合停止",
                            "別端末の先行予約あり",
                        ]
                        for seq, change in enumerate(plan.changes, start=1)
                    ]
                    log_ws.append_rows(stop_rows, value_input_option="USER_ENTERED")
                    st.error(
                        "別端末の棚卸と重なったため、書き込まず停止しました。"
                        "5分後に『データを最新化』して再入力してください。対象: "
                        + "、".join(reservation_conflicts[:10])
                    )
                    st.stop()

                # 予約判定の直前に別端末が完了した場合、その端末の予約は既に
                # 終端扱いとなる。そこで予約を取った直後にもう一度F/Gを読み、
                # 計画作成時の値と同じことを確認してから書く（CAS相当）。
                locked_live, locked_duplicates, locked_invalid = _read_live_inventory(
                    ws, last_row
                )
                prewrite_drift = find_prewrite_drift(
                    plan.changes,
                    locked_live,
                    blocked_skus=set(locked_duplicates) | set(locked_invalid),
                )
                if prewrite_drift:
                    stop_rows = []
                    stopped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for seq, change in enumerate(plan.changes, start=1):
                        actual = locked_live.get(change.sku)
                        actual_text = (
                            f"現在F:{actual.f_value} G:{actual.g_value}"
                            if actual is not None else "現在行なし"
                        )
                        stop_rows.append([
                            stopped_at,
                            "モバイル棚卸",
                            change.sku,
                            f"変更前F:{change.f_before} G:{change.g_before}",
                            actual_text,
                            f"{batch_id}:{seq:03d}",
                            "競合停止",
                            "予約取得後のライブ値変化",
                        ])
                    log_ws.append_rows(stop_rows, value_input_option="USER_ENTERED")
                    st.error(
                        "予約中に在庫が変わったため、書き込まず停止しました。"
                        "『データを最新化』して再入力してください。対象: "
                        + "、".join(prewrite_drift[:10])
                    )
                    st.stop()

                reqs = [
                    {"range": f"G{c.row_index}", "values": [[c.g_after]]}
                    for c in plan.changes
                ]
                written = sheets.safe_batch_update(
                    ws, reqs, value_input_option="USER_ENTERED"
                )
                if written != len(reqs):
                    raise RuntimeError(
                        f"在庫書込件数が一致しません（予定{len(reqs)} / 実行{written}）"
                    )
                sheets._invalidate_one("04_在庫管理")

                # ARRAYFORMULA の再計算を待ち、F/G の両方をライブ値で照合する。
                # Gだけ書けてFが目標値にならない状態は成功扱いにしない。
                live_after = {}
                duplicate_after = ()
                invalid_after = ()
                mismatches = tuple(c.sku for c in plan.changes)
                for attempt in range(5):
                    live_after, duplicate_after, invalid_after = _read_live_inventory(
                        ws, last_row
                    )
                    mismatches = find_verification_mismatches(
                        plan.changes,
                        live_after,
                        blocked_skus=set(duplicate_after) | set(invalid_after),
                    )
                    if not mismatches:
                        break
                    if attempt < 4:
                        time.sleep(1.5)

                verified = not mismatches
                status = "完了" if verified else "検証失敗"
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                audit_rows = []
                for seq, change in enumerate(plan.changes, start=1):
                    actual = live_after.get(change.sku)
                    actual_result = (
                        f"F:{actual.f_value} G:{actual.g_value}"
                        if actual is not None else "行なし"
                    )
                    audit_rows.append([
                        now,
                        "モバイル棚卸",
                        change.sku,
                        (
                            f"{change.mode}入力:{change.input_value} / "
                            f"変更前F:{change.f_before} G:{change.g_before}"
                        ),
                        (
                            f"予定F:{change.f_after} G:{change.g_after} / "
                            f"実測{actual_result}"
                        ),
                        f"{batch_id}:{seq:03d}",
                        status,
                        "送信時ライブ再読込・書込後照合",
                    ])

                audit_error = None
                try:
                    sheets.append_rows("08_ログ履歴", audit_rows)
                except Exception as exc:
                    audit_error = exc

                if not verified:
                    examples = "、".join(mismatches[:10])
                    st.error(
                        "在庫を書き込みましたが、書込後のF/G照合に失敗したため"
                        "成功扱いにしていません。再度ボタンを押さず、管理者へ"
                        f"このIDを伝えてください: {batch_id} / SKU: {examples}"
                    )
                    if audit_error:
                        st.error(f"監査ログも保存できませんでした: {audit_error}")
                else:
                    # 検証済みの値だけをセッション表示へ反映する。
                    for change in plan.changes:
                        applied[change.sku] = (change.f_after, change.g_after)

                    # 表示用スナップも即時同期し、次の再読込で古い在庫へ戻さない。
                    try:
                        snap = ss.worksheet("04_在庫スナップ")
                        snap_codes = snap.col_values(1)
                        snap_row = {}
                        for i, code in enumerate(snap_codes, start=1):
                            code = str(code).strip()
                            if code:
                                snap_row.setdefault(code, i)
                        snap_reqs = [
                            {
                                "range": f"C{snap_row[c.sku]}:D{snap_row[c.sku]}",
                                "values": [[c.f_after, c.g_after]],
                            }
                            for c in plan.changes if c.sku in snap_row
                        ]
                        if snap_reqs:
                            sheets.safe_batch_update(
                                snap, snap_reqs, value_input_option="USER_ENTERED"
                            )
                        sheets._invalidate_one("04_在庫スナップ")
                    except Exception as snap_error:
                        st.warning(f"⚠ 表示用在庫の即時更新に失敗しました: {snap_error}")

                    if audit_error:
                        st.error(
                            "在庫の照合は完了しましたが監査ログを保存できなかったため、"
                            "成功表示を出していません。再度ボタンは押さないでください。"
                            f" ID: {batch_id} / 詳細: {audit_error}"
                        )
                    else:
                        st.success(
                            f"✅ {len(plan.changes)}件反映・照合・履歴保存まで完了 "
                            f"(ID: {batch_id})"
                        )
                        st.balloons()
        except Exception as e:
            st.error(f"反映失敗: {e}")
        finally:
            if global_inventory_lock is not None:
                try:
                    global_inventory_lock.release(note="公開モバイル棚卸終了")
                except Exception as lock_error:
                    # 在庫固有の予約・書込後照合は別に残るため再加算は防げる。
                    # 共有ロックは期限で失効するが、利用者には明示する。
                    st.warning(
                        "共有在庫ロックの解放記録に失敗しました。"
                        f"最大10分で自動失効します: {lock_error}"
                    )

# 下部のページ遷移(スクロールし切った場所からでも移動できるように)
if n_pages > 1:
    st.markdown("---")
    st.caption(f"ページ {page}/{n_pages}　※移動前に「反映」を押してください(未反映の入力は消えます)")
    pcol1, pcol2, pcol3 = st.columns([1, 1, 1])
    if pcol1.button("◀ 前へ", use_container_width=True,
                    disabled=page <= 1, key="mob_count_prev"):
        st.session_state["mob_count_page"] = page - 1
        st.rerun()
    pcol2.markdown(
        f"<div style='text-align:center;line-height:52px;font-weight:700;'>"
        f"{page} / {n_pages}</div>", unsafe_allow_html=True)
    if pcol3.button("次へ ▶", use_container_width=True,
                    disabled=page >= n_pages, key="mob_count_next"):
        st.session_state["mob_count_page"] = page + 1
        st.rerun()

st.markdown("---")
st.caption("📌 実カウント=倉庫の実物数。入力した行だけが反映対象(空欄・現在庫と同じ値はスキップ)。Amazon専売(AMA専売)は自社倉庫に無いので非表示")
