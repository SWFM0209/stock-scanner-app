from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from google import genai
from fugle_marketdata import RestClient
import yfinance as yf

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    symbol: str


def load_symbols():
    with open("symbols.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def get_fugle_client():
    api_key = os.getenv("FUGLE_API_KEY")
    if not api_key:
        raise ValueError("未設定 FUGLE_API_KEY")
    return RestClient(api_key=api_key)


def get_stock_realtime(symbol: str):
    client = get_fugle_client()
    stock = client.stock

    ticker = stock.intraday.ticker(symbol=symbol)
    quote = stock.intraday.quote(symbol=symbol)

    data = {
        "ticker": ticker,
        "quote": quote
    }

    print("FUGLE DATA:", data)
    return data


def get_volume_from_yfinance(symbol: str):
    try:
        tw = f"{symbol}.TW"
        otc = f"{symbol}.TWO"

        df = yf.download(tw, period="1d", interval="1d", progress=False, auto_adjust=False)

        if df.empty:
            df = yf.download(otc, period="1d", interval="1d", progress=False, auto_adjust=False)

        if not df.empty:
            if "Volume" in df.columns:
                return int(df["Volume"].iloc[-1])

            # MultiIndex fallback
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                vol_col = [c for c in df.columns if c[0] == "Volume"]
                if vol_col:
                    return int(df[vol_col[0]].iloc[-1])

    except Exception as e:
        print("yfinance volume error:", e)

    return 0


def safe_get_close(data: dict):
    q = data.get("quote", {})
    if q.get("priceLast") is not None:
        return float(q["priceLast"])
    if q.get("closePrice") is not None:
        return float(q["closePrice"])
    raise ValueError("取不到成交價")


def safe_get_open(data: dict):
    q = data.get("quote", {})
    return (
        q.get("priceOpen")
        or q.get("openPrice")
        or None
    )


def safe_get_high(data: dict):
    q = data.get("quote", {})
    return (
        q.get("priceHigh")
        or q.get("highPrice")
        or None
    )


def safe_get_volume(data: dict, symbol: str):
    q = data.get("quote", {})

    vol = (
        q.get("tradeVolume")
        or q.get("volume")
        or 0
    )

    if vol == 0:
        vol = get_volume_from_yfinance(symbol)

    return int(vol)


def calc_score(close, open_price, high_price, volume):
    strength = 0.0
    position = 0.0

    if open_price and open_price != 0:
        strength = (close - open_price) / open_price

    if high_price and high_price != 0:
        position = close / high_price

    vol_score = volume / 1_000_000
    score = strength * 100 + position * 20 + vol_score * 0.2

    return round(score, 3), round(strength, 3)


def make_local_ai_text(rule_result):
    lines = []

    lines.append(
        f"• {rule_result['symbol']} 目前分數為 {rule_result['score']}，強度為 {rule_result['strength']}。"
    )

    if rule_result["strength"] > 0:
        lines.append("• 現價相對偏強，屬於盤中仍有動能的型態。")
    else:
        lines.append("• 目前動能不明顯，需保守看待。")

    if rule_result["volume"] and rule_result["volume"] > 0:
        lines.append("• 有成交量可供追蹤，後續可觀察量價是否同步。")
    else:
        lines.append("• 目前量能資訊偏弱，判讀可靠度較低。")

    if rule_result["risks"]:
        lines.append("• 主要風險：" + "、".join(rule_result["risks"]))
    else:
        lines.append("• 明顯風險不多，但仍需留意盤中波動。")

    lines.append("• 建議：先觀察是否續強，再決定是否進一步追蹤。")

    return "\n".join(lines)


def analyze_stock_with_gemini(rule_result):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "llm_analysis": make_local_ai_text(rule_result),
            "llm_model": "local-fallback-no-key"
        }

    client = genai.Client(api_key=api_key)

    prompt = f"""
你是一個台股短線交易分析助理。

股票代號：{rule_result["symbol"]}
目前價格：{rule_result["close"]}
開盤價：{rule_result["open"]}
日內高點：{rule_result["high"]}
成交量：{rule_result["volume"]}
強度（strength）：{rule_result["strength"]}
綜合評分（score）：{rule_result["score"]}

請用繁體中文簡單回答：
1. 這檔股票目前強在哪
2. 有哪些風險
3. 接下來該怎麼觀察或操作

請用條列式，精簡但有重點。
"""

    models = ["gemini-2.5-flash", "gemini-2.0-flash"]

    for m in models:
        try:
            res = client.models.generate_content(
                model=m,
                contents=prompt
            )
            text = res.text if hasattr(res, "text") and res.text else str(res)
            return {
                "llm_analysis": text,
                "llm_model": m
            }
        except Exception as e:
            print(f"Gemini model {m} failed:", e)

    return {
        "llm_analysis": make_local_ai_text(rule_result),
        "llm_model": "local-fallback"
    }


def analyze_stock_logic(symbol: str):
    if not str(symbol).isdigit():
        return {"symbol": symbol, "error": "symbol錯誤"}

    data = get_stock_realtime(symbol)

    close = safe_get_close(data)
    open_price = safe_get_open(data)
    high_price = safe_get_high(data)
    volume = safe_get_volume(data, symbol)

    score, strength = calc_score(close, open_price, high_price, volume)

    pros = []
    risks = []

    if open_price and close > open_price:
        pros.append("站上開盤價")
    if high_price and close >= high_price * 0.98:
        pros.append("接近日內高點")
    if volume > 0:
        pros.append("有量")

    if open_price and close < open_price:
        risks.append("跌破開盤")
    if high_price and close < high_price * 0.95:
        risks.append("回落")
    if volume == 0:
        risks.append("無量")

    return {
        "symbol": symbol,
        "close": close,
        "open": open_price,
        "high": high_price,
        "volume": volume,
        "strength": strength,
        "score": score,
        "stage": "即時分析",
        "pros": pros,
        "risks": risks,
        "suggestion": "觀察量價變化"
    }


@app.get("/")
def root():
    return {"ok": True}


@app.get("/scan")
def scan():
    symbols = load_symbols()
    result = []

    for s in symbols:
        try:
            data = analyze_stock_logic(s)
            result.append(data)
        except Exception as e:
            print(f"scan error {s}: {e}")

    result = sorted(result, key=lambda x: x["score"], reverse=True)

    return {"count": len(result), "data": result}


@app.get("/company/{symbol}")
def get_company(symbol: str):
    return {
        "symbol": symbol,
        "name": "示範公司",
        "industry": "電子業",
        "market": "上市/上櫃",
        "capital": "待串真實資料",
        "chairman": "待串真實資料",
        "general_manager": "待串真實資料",
        "description": "目前為公司基本資料 API 骨架。"
    }


@app.post("/ai/analyze")
def ai(req: AnalyzeRequest):
    try:
        r = analyze_stock_logic(req.symbol)
        if "error" in r:
            return r

        llm = analyze_stock_with_gemini(r)

        return {**r, **llm}

    except Exception as e:
        return {"error": str(e)}
