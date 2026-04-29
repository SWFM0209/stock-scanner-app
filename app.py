import streamlit as st
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go

# =========================
# ✅ 基本設定
# =========================
st.set_page_config(page_title="詹姆士選股", layout="wide")

# =========================
# ✅ 讀取 JSON（Render 修正版）
# =========================
BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "latest_scan_result.json"

if not DATA_PATH.exists():
    st.warning("尚未找到 latest_scan_result.json，請先跑掃描")
    st.stop()

with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

# =========================
# UI 標題
# =========================
st.title("📈 詹姆士選股")
st.caption("雙層策略：候選股 + 確認訊號 + K線圖")

st.markdown(f"""
更新時間：{data.get("updated_at","-")}
  
掃描總數：{data.get("total",0)}  
""")

# =========================
# 資料
# =========================
confirmed = data.get("confirmed", [])
candidates = data.get("candidates", [])

# =========================
# 確認訊號
# =========================
st.subheader(f"🔥 確認訊號：{len(confirmed)} 檔")

if len(confirmed) == 0:
    st.info("目前沒有確認訊號")

for stock in confirmed:
    with st.container():
        st.markdown(f"""
### {stock['symbol']} {stock.get('name','')}

收盤：{stock['close']}  
60日高點：{stock['h1']}  
MA5 / MA10 / MA20：{stock['ma5']} / {stock['ma10']} / {stock['ma20']}  
成交量：{stock['volume']:,}  
        """)

# =========================
# 候選股
# =========================
st.subheader(f"🟡 候選股：{len(candidates)} 檔")

for stock in candidates:
    with st.container():
        st.markdown(f"""
### {stock['symbol']} {stock.get('name','')}

收盤：{stock['close']}  
60日高點：{stock['h1']}  
MA5 / MA10 / MA20：{stock['ma5']} / {stock['ma10']} / {stock['ma20']}  
成交量：{stock['volume']:,}  
        """)

# =========================
# 🔥 K線圖（單一選股）
# =========================
st.divider()
st.subheader("📊 K線圖")

symbol = st.text_input("輸入股票代碼（例如 2330）", "2330")

# 假資料（如果你之後要接 Fugle API 可換掉）
def generate_fake_kline():
    df = pd.DataFrame({
        "date": pd.date_range(end=pd.Timestamp.today(), periods=60),
        "open": pd.Series(range(100,160)),
        "high": pd.Series(range(102,162)),
        "low": pd.Series(range(98,158)),
        "close": pd.Series(range(101,161))
    })
    return df

df = generate_fake_kline()

fig = go.Figure(data=[go.Candlestick(
    x=df['date'],
    open=df['open'],
    high=df['high'],
    low=df['low'],
    close=df['close']
)])

fig.update_layout(
    template="plotly_dark",
    height=500,
    margin=dict(l=10, r=10, t=30, b=10)
)

st.plotly_chart(fig, use_container_width=True)
