
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

STOCK_NAMES = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2303": "聯電",
    "2603": "長榮",
    "2882": "國泰金",
    "2891": "中信金",
    "2408": "南亞科",
    "2308": "台達電",
    "3231": "緯創",
    "3481": "群創",
    "2409": "友達",
    "2301": "光寶科",
    "2357": "華碩",
    "2382": "廣達",
    "2379": "瑞昱",
    "6669": "緯穎",
    "3034": "聯詠",
    "3711": "日月光投控",
    "2881": "富邦金",
}

DEFAULT_SYMBOLS = [
    "2330", "2317", "2454", "2303", "2603",
    "3481", "2409", "2308", "3231", "6669"
]

def load_symbols():
    if os.path.exists("symbols.txt"):
        with open("symbols.txt", "r", encoding="utf-8") as f:
            symbols = [line.strip() for line in f if line.strip()]
            if symbols:
                return symbols
    return DEFAULT_SYMBOLS

def get_fugle_client():
    api_key = os.getenv("FUGLE_API_KEY")
    if not api_key:
        raise ValueError("未設定 FUGLE_API_KEY")
    return RestClient(api_key=api_key)

def get_stock_data(symbol: str):
    client = get_fugle_client()
    stock = client.stock

    ticker = {}
    quote = {}
    stats = {}

    try:
        ticker = stock.intraday.ticker(symbol=symbol)
    except Exception as e:
        print(f"ticker error {symbol}: {e}")

    try:
        quote = stock.intraday.quote(symbol=symbol)
    except Exception as e:
        print(f"quote error {symbol}: {e}")

    try:
        stats = stock.historical.stats(symbol=symbol)
    except Exception as e:
        print(f"stats error {symbol}: {e}")

    return {
        "ticker": ticker or {},
        "quote": quote or {},
        "stats": stats or {}
    }

def pick_value(*values):
    for v in values:
        if v is not None:
            return v
    return None

def analyze_stock_logic(symbol: str):
    if not str(symbol).isdigit():
        return {"symbol": symbol, "error": "symbol錯誤"}

    data = get_stock_data(symbol)
    q = data.get("quote", {})
    s = data.get("stats", {})
    t = data.get("ticker", {})

    name = (
        t.get("name")
        or t.get("symbolName")
        or q.get("name")
        or q.get("symbolName")
        or s.get("name")
        or s.get("symbolName")
        or STOCK_NAMES.get(symbol)
        or symbol
    )

    close = pick_value(
        q.get("priceLast"),
        q.get("closePrice"),
        s.get("closePrice"),
        t.get("closePrice")
    )

    open_price = pick_value(
        q.get("priceOpen"),
        q.get("openPrice"),
        s.get("openPrice"),
        t.get("openPrice")
    )

    high_price = pick_value(
        q.get("priceHigh"),
        q.get("highPrice"),
        s.get("highPrice"),
        t.get("highPrice")
    )

    volume = pick_value(
        q.get("tradeVolume"),
        q.get("volume"),
        s.get("tradeVolume"),
        s.get("volume"),
        t.get("tradeVolume"),
        t.get("volume")
    )

    if close is None:
        raise ValueError("取不到成交價")

    close = float(close)
    open_price = float(open_price) if open_price is not None else None
    high_price = float(high_price) if high_price is not None else None
    volume = int(volume) if volume is not None else 0

    strength = 0
    if open_price and open_price != 0:
        strength = round((close - open_price) / open_price, 3)

    score = 0
    if high_price and high_price != 0:
        score += close / high_price * 50
    if open_price and open_price != 0:
        score += max((close - open_price) / open_price * 100, 0)
    score += min(volume / 1_000_000, 20)

    score = round(score, 3)

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
        "name": name,
        "close": close,
        "open": open_price,
        "high": high_price,
        "volume": volume,
        "strength": strength,
        "score": score,
        "pros": pros,
        "risks": risks,
        "suggestion": "觀察量價變化"
    }

def make_local_ai_text(r):
    return f"""【強勢原因】
- {r["name"]}（{r["symbol"]}）目前分數為 {r["score"]}。
- 目前價格為 {r["close"]}，成交量為 {r["volume"]}。

【風險】
- {("、".join(r["risks"])) if r["risks"] else "暫無明顯風險，但仍需留意盤中波動。"}

【操作建議】
- 先觀察量價是否延續，不建議單靠一次掃描結果追高。
"""

def analyze_stock_with_gemini(r):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {
            "llm_analysis": make_local_ai_text(r),
            "llm_model": "local-fallback-no-key"
        }

    client = genai.Client(api_key=api_key)

    prompt = f"""
你是一個台股短線交易分析助理。
請全部使用繁體中文，不要使用英文，不要加客套開頭。

股票代號：{r["symbol"]}
股票名稱：{r["name"]}
目前價格：{r["close"]}
開盤價：{r["open"]}
日內高點：{r["high"]}
成交量：{r["volume"]}
強度：{r["strength"]}
分數：{r["score"]}

請用以下格式輸出：

【強勢原因】
- ...

【風險】
- ...

【操作建議】
- ...
"""

    for model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        try:
            res = client.models.generate_content(model=model, contents=prompt)
            return {
                "llm_analysis": res.text,
                "llm_model": model
            }
        except Exception as e:
            print(f"Gemini failed {model}: {e}")

    return {
        "llm_analysis": make_local_ai_text(r),
        "llm_model": "local-fallback"
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"ok": True, "message": "stock scanner api running"}

@app.get("/scan")
def scan():
    symbols = load_symbols()
    result = []

    for symbol in symbols:
        try:
            result.append(analyze_stock_logic(symbol))
        except Exception as e:
            print(f"scan error {symbol}: {e}")

    result = sorted(result, key=lambda x: x.get("score", 0), reverse=True)
    return {"count": len(result), "data": result}

@app.post("/ai/analyze")
def ai(req: AnalyzeRequest):
    try:
        r = analyze_stock_logic(req.symbol)
        llm = analyze_stock_with_gemini(r)
        return {**r, **llm}
    except Exception as e:
        return {"error": str(e)}

