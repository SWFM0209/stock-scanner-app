import json, re
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go

RESULT_PATH = Path.home() / "latest_scan_result.json"
NAME_FILES = [
    Path.home() / "stock_names_full.csv",
    Path.home() / "stock_names_clean.csv",
    Path.home() / "stock_names.csv",
]

def load_stock_names():
    names = {}
    for path in NAME_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = re.split(r"[,\t]", line.strip())
            if len(parts) >= 2 and parts[0].isdigit():
                names[parts[0]] = parts[1].strip()
    return names

def fmt_num(v):
    try:
        return f"{float(v):,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "-"

def fmt_int(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return "-"

def draw_kline(kbars, title):
    if not kbars:
        st.info("沒有 K 線資料")
        return

    fig = go.Figure(data=[go.Candlestick(
        x=[x["date"] for x in kbars],
        open=[x["open"] for x in kbars],
        high=[x["high"] for x in kbars],
        low=[x["low"] for x in kbars],
        close=[x["close"] for x in kbars],
    )])

    fig.update_layout(
        title=title,
        height=360,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
    )
    st.plotly_chart(fig, use_container_width=True)

STOCK_NAMES = load_stock_names()

st.set_page_config(page_title="詹姆士選股", page_icon="📈", layout="wide")

st.markdown("""
<style>
.stApp { background: #0b0f19; color: #e5e7eb; }
.block-container { max-width: 1180px; padding-top: 2rem; }
.stock-card {
    background: #111827;
    border: 1px solid #263244;
    border-radius: 20px;
    padding: 18px 20px;
    margin-bottom: 14px;
}
.stock-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-top: 14px;
}
.cell {
    background: #020617;
    border: 1px solid #1f2937;
    border-radius: 14px;
    padding: 12px;
}
.cell-label { color: #94a3b8; font-size: 12px; }
.cell-value { font-weight: 800; font-size: 16px; margin-top: 4px; }
.badge {
    display:inline-block;
    padding: 6px 10px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 800;
    margin-top: 4px;
}
.blue { background: rgba(59,130,246,.18); color: #60a5fa; }
.green { background: rgba(34,197,94,.18); color: #4ade80; }
</style>
""", unsafe_allow_html=True)

st.title("詹姆士選股")
st.caption("雙層策略｜候選股 + 確認訊號 + K線圖")

if not RESULT_PATH.exists():
    st.info("尚未找到 latest_scan_result.json，請先跑：python3 ~/daily_scan.py")
    st.stop()

data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
matched = data.get("matched", [])
candidates = data.get("candidates", [])

c1, c2, c3 = st.columns([1, 1, 1])
with c1:
    if st.button("重新整理", use_container_width=True):
        st.rerun()
with c2:
    show_mode = st.selectbox("顯示模式", ["全部", "只看確認訊號", "只看候選股"], index=0)
with c3:
    sort_mode = st.selectbox("排序", ["成交量由大到小", "接近60日高點", "代號排序"], index=0)

st.metric("掃描總數", data.get("total", "-"))
st.caption(f"更新時間：{data.get('updated_at', '-')}")
st.caption(f"失敗：{data.get('failed_count', '-')}")

def near_high_ratio(r):
    try:
        return float(r.get("last", 0)) / float(r.get("h60", 1))
    except Exception:
        return 0

def sort_rows(rows):
    if sort_mode == "成交量由大到小":
        return sorted(rows, key=lambda r: int(r.get("volume") or 0), reverse=True)
    if sort_mode == "接近60日高點":
        return sorted(rows, key=near_high_ratio, reverse=True)
    return sorted(rows, key=lambda r: str(r.get("symbol", "")))

def render_card(r, kind):
    symbol = str(r.get("symbol", ""))
    name = STOCK_NAMES.get(symbol, "")
    badge = "確認訊號" if kind == "confirmed" else "候選股"
    color = "green" if kind == "confirmed" else "blue"

    try:
        near = f"{near_high_ratio(r) * 100:.2f}%"
    except Exception:
        near = "-"

    st.markdown(f"""
    <div class="stock-card">
      <h2>{symbol} {name}</h2>
      <span class="badge {color}">{badge}</span>
      <div class="stock-grid">
        <div class="cell"><div class="cell-label">收盤</div><div class="cell-value">{fmt_num(r.get("last"))}</div></div>
        <div class="cell"><div class="cell-label">60日高點</div><div class="cell-value">{fmt_num(r.get("h60"))}</div></div>
        <div class="cell"><div class="cell-label">接近高點</div><div class="cell-value">{near}</div></div>
        <div class="cell"><div class="cell-label">成交量</div><div class="cell-value">{fmt_int(r.get("volume"))}</div></div>
        <div class="cell"><div class="cell-label">BreakState</div><div class="cell-value">{r.get("break_state")}</div></div>
      </div>
      <div class="stock-grid">
        <div class="cell"><div class="cell-label">MA5</div><div class="cell-value">{fmt_num(r.get("ma5"))}</div></div>
        <div class="cell"><div class="cell-label">MA10</div><div class="cell-value">{fmt_num(r.get("ma10"))}</div></div>
        <div class="cell"><div class="cell-label">MA20</div><div class="cell-value">{fmt_num(r.get("ma20"))}</div></div>
        <div class="cell"><div class="cell-label">Anchor</div><div class="cell-value">{fmt_num(r.get("strategy_anchor"))}</div></div>
        <div class="cell"><div class="cell-label">條件</div><div class="cell-value">{r.get("condition1")} / {r.get("condition2")} / {r.get("condition3")}</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander(f"查看 {symbol} K線圖"):
        draw_kline(r.get("kbars", []), f"{symbol} {name}")

if show_mode in ["全部", "只看確認訊號"]:
    st.header(f"確認訊號：{len(matched)} 檔")
    if not matched:
        st.info("目前沒有確認訊號。")
    else:
        for r in sort_rows(matched):
            render_card(r, "confirmed")

if show_mode in ["全部", "只看候選股"]:
    st.header(f"候選股：{len(candidates)} 檔")
    if not candidates:
        st.info("目前沒有候選股。")
    else:
        for r in sort_rows(candidates):
            render_card(r, "candidate")
