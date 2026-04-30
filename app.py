import streamlit as st
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="詹姆士選股", layout="wide")

BASE_DIR = Path(__file__).parent
DATA_PATH = BASE_DIR / "latest_scan_result.json"


@st.cache_data(ttl=86400)
def load_stock_name_map():
    name_map = {}

    urls = [
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
    ]

    for url in urls:
        try:
            tables = pd.read_html(url)
            df = tables[0]

            for value in df.iloc[:, 0].dropna():
                text = str(value).strip()
                parts = text.split()

                if len(parts) >= 2 and parts[0].isdigit():
                    name_map[parts[0]] = parts[1]
        except Exception:
            pass

    return name_map


def get_value(stock, *keys, default="無資料"):
    for key in keys:
        if key in stock and stock[key] is not None and stock[key] != "":
            return stock[key]
    return default


def format_volume(value):
    if value in ["無資料", None, ""]:
        return "無資料"
    try:
        return f"{int(float(value)):,}"
    except Exception:
        return str(value)


def render_stock_card(stock, stock_name_map):
    symbol = str(get_value(stock, "symbol", "code", "stock_id", default="-"))

    name = get_value(
        stock,
        "name",
        "stock_name",
        "company_name",
        "股票名稱",
        "名稱",
        "公司名稱",
        default=""
    )

    if not name:
        name = stock_name_map.get(symbol, "")

    close = get_value(stock, "close", "Close", "last", "收盤", "收盤價")
    h1 = get_value(stock, "h1", "H1", "high_60", "high60", "60_high", "h60", "60日高點")
    ma5 = get_value(stock, "ma5", "MA5", "ma_5")
    ma10 = get_value(stock, "ma10", "MA10", "ma_10")
    ma20 = get_value(stock, "ma20", "MA20", "ma_20")
    volume = get_value(stock, "volume", "Volume", "成交量")

    title = f"{symbol} {name}" if name else symbol

    st.markdown(f"""
### {title}

收盤：{close}  
60日高點：{h1}  
MA5 / MA10 / MA20：{ma5} / {ma10} / {ma20}  
成交量：{format_volume(volume)}  
    """)


if not DATA_PATH.exists():
    st.warning("尚未找到 latest_scan_result.json，請先跑掃描")
    st.stop()

with open(DATA_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

stock_name_map = load_stock_name_map()
st.caption(f"股票名稱表載入：{len(stock_name_map)} 筆")
st.title("📈 詹姆士選股")
st.caption("雙層策略：候選股 + 確認訊號 + K線圖")

st.markdown(f"""
更新時間：{data.get("updated_at", "-")}

掃描總數：{data.get("total", data.get("progress", 0))}
""")

confirmed = data.get("confirmed", data.get("matched", []))
candidates = data.get("candidates", [])

st.subheader(f"🔥 確認訊號：{len(confirmed)} 檔")

if len(confirmed) == 0:
    st.info("目前沒有確認訊號")
else:
    for stock in confirmed:
        with st.container():
            render_stock_card(stock, stock_name_map)

st.subheader(f"🟡 候選股：{len(candidates)} 檔")

if len(candidates) == 0:
    st.info("目前沒有候選股")
else:
    for stock in candidates:
        with st.container():
            render_stock_card(stock, stock_name_map)

st.divider()
st.subheader("📊 K線圖")

symbol = st.text_input("輸入股票代碼（例如 2330）", "2330")


def generate_fake_kline():
    return pd.DataFrame({
        "date": pd.date_range(end=pd.Timestamp.today(), periods=60),
        "open": pd.Series(range(100, 160)),
        "high": pd.Series(range(102, 162)),
        "low": pd.Series(range(98, 158)),
        "close": pd.Series(range(101, 161)),
    })


df = generate_fake_kline()

fig = go.Figure(data=[go.Candlestick(
    x=df["date"],
    open=df["open"],
    high=df["high"],
    low=df["low"],
    close=df["close"],
)])

fig.update_layout(
    template="plotly_dark",
    height=500,
    margin=dict(l=10, r=10, t=30, b=10),
)

st.plotly_chart(fig, use_container_width=True)
