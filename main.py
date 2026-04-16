from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from google import genai
from fugle_marketdata import RestClient

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

    return {
        "ticker": ticker,
        "quote": quote
    }

def safe_get_close(data: dict):
    q = data.get("quote", {})
    if q.get("priceLast") is not None:
        return float(q["priceLast"])
    if q.get("closePrice") is not None:
        return float(q["closePrice"])
    raise ValueError("取不到成交價")

def safe_get_volume(data: dict):
    q = data.get("quote", {})
    if q.get("tradeVolume") is not None:
        return int(q["tradeVolume"])
    if q.get("volume") is not None:
        return int(q["volume"])
    return 0

def safe_get_open(data: dict):
    q = data.get("quote", {})
    if q.get("priceOpen") is not None:
        return float(q["priceOpen"])
    return None

def safe_get_high(data: dict):
    q = data.get("quote", {})
    if q.get("priceHigh") is not None:
        return float(q["priceHigh"])
    return None

def calc_score(close, open_price, high_price, volume):
    strength = 0
    position = 0

    if open_price and open_price != 0:
        strength = (close - open_price) / open_price

    if high_price and high_price != 0:
        position = close / high_price

    vol_score = volume / 1_000_000

    score = strength * 100 + position * 20 + vol_score * 0.2

    return round(score, 3), round(strength, 3)

def analyze_stock_logic(symbol: str):
    if not str(symbol).isdigit():
        return {"symbol": symbol, "error": "symbol錯誤"}

    data = get_stock_realtime(symbol)

    close = safe_get_close(data)
    volume = safe_get_volume(data)
    open_price = safe_get_open(data)
    high_price = safe_get_high(data)

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

def analyze_stock_with_gemini(rule_result):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"llm_analysis": "未設定API KEY"}

    client = genai.Client(api_key=api_key)

    prompt = f"""
股票：{rule_result["symbol"]}
價格：{rule_result["close"]}
成交量：{rule_result["volume"]}
score：{rule_result["score"]}

請用繁體中文簡單說：
1. 強在哪
2. 風險
3. 建議
"""

    models = ["gemini-2.5-flash", "gemini-2.0-flash"]

    for m in models:
        try:
            res = client.models.generate_content(
                model=m,
                contents=prompt
            )
            return {"llm_analysis": res.text, "model": m}
        except Exception as e:
            err = str(e)

    return {"llm_analysis": f"AI失敗:{err}"}

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
        except:
            pass

    result = sorted(result, key=lambda x: x["score"], reverse=True)

    return {"count": len(result), "data": result}

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
