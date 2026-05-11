"""
01_設定 シート 編集ページ

GASとPythonバッチが参照する設定値を編集できる。
- 在庫判定閾値 (過剰/余裕/注意/要発注/危険ライン)
- 発注設計 (発注サイクル/安全在庫日数/リードタイム/月間発注上限)
- 販売速度 (集計期間/急増・急減倍率)
- 春節カレンダー
- LINE通知時刻
- 全SKU自動PUSHモード
"""
import pandas as pd
import streamlit as st

from lib import sheets, ui

st.set_page_config(page_title="設定", page_icon="⚙️", layout="wide")
st.title("⚙️ 01_設定 (編集可)")
ui.sidebar_common(this_sheet="01_設定")

st.caption(
    "GASとPython朝バッチが読む設定値。**B列(値)** だけ編集してください。"
    "編集→Enterで自動保存。空白行はB列無視。"
)

sh = sheets.get_spreadsheet()
ws = sh.worksheet("01_設定")
all_v = ws.get_all_values()

if not all_v:
    st.warning("01_設定 が空です")
    st.stop()

# 4列前提 (A:項目, B:値, C:単位, D:説明)
rows_data = []
for i, r in enumerate(all_v, start=1):
    a = r[0] if len(r) > 0 else ""
    b = r[1] if len(r) > 1 else ""
    c = r[2] if len(r) > 2 else ""
    d = r[3] if len(r) > 3 else ""
    rows_data.append({"行": i, "項目": a, "値": b, "単位": c, "説明": d})

df = pd.DataFrame(rows_data)

# 編集テーブル: 値列だけ編集可
edited = st.data_editor(
    df,
    use_container_width=True,
    height=700,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "行":   st.column_config.NumberColumn(label="🔒 行", disabled=True, width="small"),
        "項目": st.column_config.TextColumn(label="🔒 A 項目", disabled=True),
        "値":   st.column_config.TextColumn(label="🟢 B 値"),
        "単位": st.column_config.TextColumn(label="🔒 C 単位", disabled=True),
        "説明": st.column_config.TextColumn(label="🔒 D 説明", disabled=True),
    },
    key="settings_editor",
)

# 自動保存
state = st.session_state.get("settings_editor", {})
if state.get("edited_rows"):
    try:
        requests = []
        for ri_str, changes in state["edited_rows"].items():
            ri = int(ri_str)  # 0-indexed dataframe row
            row_num = df.iloc[ri]["行"]  # スプシ行番号(1-indexed)
            if "値" in changes:
                requests.append({
                    "range": f"B{row_num}",
                    "values": [[changes["値"]]],
                })
        if requests:
            ws.batch_update(requests, value_input_option="USER_ENTERED")
            sheets._invalidate_one("01_設定")
            st.toast(f"💾 自動保存 {len(requests)}件", icon="✅")
            st.rerun()
    except Exception as e:
        st.error(f"❌ 自動保存失敗: {e}")
else:
    st.caption("✅ 変更なし(B列を編集→Enterで自動保存)")
