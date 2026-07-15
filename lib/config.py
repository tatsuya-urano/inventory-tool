"""
全ページ共通の設定値
"""
from pathlib import Path

# Google Sheets
SPREADSHEET_ID = "1f-dLliies_Tr7CDNSQ_48itZ9W5tYEzr4O93jh2uPcQ"
SERVICE_ACCOUNT_JSON = (
    Path(__file__).parent.parent / ".streamlit" / "service_account.json"
)

# シート名（GAS の SHEETS と揃える）
SHEET_INVENTORY     = "04_在庫管理"
# 04_在庫管理は TODAY()依存の重い数式で読込に8分半かかる。表示用は家PCバッチが
# 数式ゼロで焼き付けた軽量スナップ(0.4秒)を読む。書込は本物の04へ。
SHEET_INV_SNAPSHOT  = "04_在庫スナップ"
SHEET_SALES         = "05_売上管理"
SHEET_SUMMARY       = "15_サマリ"
SHEET_PRODUCT_MASTER = "03_商品マスタ参照"
SHEET_DISCONTINUED  = "17_終売SKU"

# 在庫管理シート
INV_HEADER_ROW = 6   # 1-indexed
INV_DATA_START = 7   # 1-indexed

# 売上管理シート
SALES_HEADER_ROW = 1
SALES_DATA_START = 2

# 認証スコープ（読み書き）
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# キャッシュ秒（15分）— 編集時はそのシートだけ自動無効化される。
# 手動リロードボタンで強制更新可。
# 旧3600(1時間)はCloud無料枠(~1GB)で古いDataFrameがメモリに居座り、
# 時間経過でOOM→「Oh no.」→Reboot→再発 のループを招いていた。TTLを短くして
# 期限切れキャッシュを早めに解放し、メモリ滞留を減らす(再発間隔を延ばす)。
CACHE_TTL_SECONDS = 900

# ステータスアイコン
STATUS_DANGER   = "🔴危険"
STATUS_ORDER    = "🟠要発注"
STATUS_CAUTION  = "🟡注意"
STATUS_ABUNDANT = "🟢余裕"
STATUS_EXCESS   = "🟣過剰"
STATUS_OUT      = "⚫在庫切れ"
STATUS_END      = "🚫終売"
# 発注見送りは独立ステータスではなく 17_終売SKU の「種別=発注見送り」で表現する
