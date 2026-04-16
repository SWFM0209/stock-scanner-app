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
    quote = data.get("quote", {})
    if quote.get("priceLast") is not None:
        return float(quote["priceLast"])
    if quote.get("closePrice") is not None:
        return float(quote["closePrice"])
    raise ValueError("取不到最新成交價")


def safe_get_volume(data: dict):
    quote = data.get("quote", {})
    if quote.get("tradeVolume") is not None:
        return int(quote["tradeVolume"])
    if quote.get("volume") is not None:
        return int(quote["volume"])
    return 0


def safe_get_open(data: dict):
    quote = data.get("quote", {})
    if quote.get("priceOpen") is not None:
        return float(quote["priceOpen"])
    return None


def safe_get_high(data: dict):
    quote = data.get("quote", {})
    if quote.get("priceHigh") is not None:
        return float(quote["priceHigh"])
    return None


def calc_realtime_score(close: float, open_price, high_price, volume: int):
    change_strength = 0.0
    intraday_position = 0.0

    if open_price and open_price != 0:
        change_strength = (close - open_price) / open_price

    if high_price and high_price != 0:
        intraday_position = close / high_price

    volume_score = volume / 1_000_000

    score = (
        change_strength * 100
        + intraday_position * 20
        + volume_score * 0.2
    )

    return round(score, 3), round(change_strength, 3)


def build_stock_result(symbol: str, data: dict):
    close = safe_get_close(data)
    volume = safe_get_volume(data)
    open_price = safe_get_open(data)
    high_price = safe_get_high(data)

    score, strength = calc_realtime_score(
        close=close,
        open_price=open_price,
        high_price=high_price,
        volume=volume
    )

    return {
        "symbol": symbol,
        "close": close,
        "volume": volume,
        "open": open_price,
        "high": high_price,
        "strength": strength,
        "score": score,
        "reason": "富果即時行情掃描"
    }


def run_post_market_scan():
    symbols = load_symbols()
    matched = []

    for idx, symbol in enumerate(symbols, start=1):
        try:
            print(f"[{idx}/{len(symbols)}] scanning {symbol}")
            data = get_stock_realtime(symbol)
            matched.append(build_stock_result(symbol, data))
        except Exception as e:
            print(f"error: {symbol} - {e}")

    matched = sorted(
        matched,
        key=lambda x: (x["score"], x["volume"]),
        reverse=True
    )

    return matched


def analyze_stock_logic(symbol: str):
    if not str(symbol).isdigit():
        return {
            "symbol": symbol,
            "error": "symbol 格式錯誤，請輸入股票代號"
        }

    data = get_stock_realtime(symbol)
    close = safe_get_close(data)
    volume = safe_get_volume(data)
    open_price = safe_get_open(data)
    high_price = safe_get_high(data)

    score, strength = calc_realtime_score(
        close=close,
        open_price=open_price,
        high_price=high_price,
        volume=volume
    )

    pros = []
    risks = []

    if open_price is not None and close > open_price:
        pros.append("現價高於開盤價，日內偏強")
    if high_price is not None and close >= high_price * 0.98:
        pros.append("目前價格接近日內高點")
    if volume > 0:
        pros.append("有即時成交量可供追蹤")

    if open_price is not None and close < open_price:
        risks.append("現價低於開盤價，日內轉弱風險存在")
    if high_price is not None and close < high_price * 0.95:
        risks.append("距離日內高點有明顯回落")
    if volume == 0:
        risks.append("成交量不足，判讀可靠度較低")

    suggestion = "可列入觀察名單，搭配盤中量價變化再決定是否進一步追蹤。"

    return {
        "symbol": symbol,
        "close": close,
        "open": open_price,
        "high": high_price,
        "volume": volume,
        "strength": strength,
        "score": score,
        "stage": "富果即時行情分析",
        "pros": pros,
        "risks": risks,
        "suggestion": suggestion
    }


def analyze_stock_with_gemini(rule_result: dict):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"llm_analysis": "未設定 GEMINI_API_KEY"}

    client = genai.Client(api_key=api_key)

    prompt = f"""
你是一個台股短線技術分析助理。

股票：{rule_result["symbol"]}
目前價格：{rule_result["close"]}
開盤價：{rule_result.get("open")}
日內高點：{rule_result.get("high")}
成交量：{rule_result["volume"]}
score：{rule_result["score"]}
strength：{rule_result["strength"]}
分析階段：{rule_result["stage"]}

優點：
{chr(10).join(rule_result["pros"]) if rule_result["pros"] else "無"}

風險：
{chr(10).join(rule_result["risks"]) if rule_result["risks"] else "無"}

請用繁體中文、簡潔白話回答：
1. 這檔目前強在哪
2. 主要風險
3. 接下來該怎麼觀察
"""

    models_to_try = ["gemini-1.5-flash", "gemini-1.5-pro"]
    last_error = "未知錯誤"

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return {"llm_analysis": response.text}
        except Exception as e:
            last_error = str(e)

    return {"llm_analysis": f"AI 分析暫時無法使用：{last_error}"}


@app.get("/")
def root():
    return {"message": "Stock app backend is running"}


@app.get("/scan")
def scan_stocks():
    results = run_post_market_scan()
    return {
        "count": len(results),
        "results": results
    }


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
def ai_analyze(req: AnalyzeRequest):
    try:
        rule_result = analyze_stock_logic(req.symbol)

        if "error" in rule_result:
            return rule_result

        llm = analyze_stock_with_gemini(rule_result)

        return {
            **rule_result,
            **llm
        }

    except Exception as e:
        return {
            "symbol": req.symbol,
            "error": str(e)
        }
