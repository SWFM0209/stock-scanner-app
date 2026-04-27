from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import requests
from datetime import date, timedelta
from google import genai

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://api.fugle.tw/marketdata/v1.0"

STOCK_NAMES = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2303": "聯電",
    "2603": "長榮", "2882": "國泰金", "2891": "中信金", "2408": "南亞科",
    "2308": "台達電", "3231": "緯創", "3481": "群創", "2409": "友達",
    "2301": "光寶科", "2357": "華碩", "2382": "廣達", "2379": "瑞昱",
    "6669": "緯穎", "3034": "聯詠", "3711": "日月光投控", "2881": "富邦金",
}

DEFAULT_SYMBOLS = ["2330", "2317", "2454", "2303", "2603", "3481", "2409", "2308", "3231", "6669"]


class AnalyzeRequest(BaseModel):
    symbol: str


def load_symbols():
    if os.path.exists("symbols.txt"):
        with open("symbols.txt", "r", encoding="utf-8") as f:
            symbols = [x.strip() for x in f if x.strip()]
            if symbols:
                return symbols
    return DEFAULT_SYMBOLS


def fugle_get(path, params=None):
    api_key = os.getenv("FUGLE_API_KEY")
    if not api_key:
        raise ValueError("未設定 FUGLE_API_KEY")

    r = requests.get(
        BASE_URL + path,
        headers={"X-API-KEY": api_key, "Accept": "application/json"},
        params=params,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def load_kbars(symbol: str, lookback_days: int = 180):
    to_date = date.today()
    from_date = to_date - timedelta(days=lookback_days)

    data = fugle_get(
        f"/stock/historical/candles/{symbol}",
        {
            "timeframe": "D",
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "fields": "open,high,low,close,volume",
            "sort": "asc",
        },
    )

    candles = data.get("data") or data.get("candles") or []
    if isinstance(candles, dict):
        candles = candles.get("candles", [])

    rows = []
    for x in candles:
        try:
            rows.append({
                "open": float(x["open"]),
                "high": float(x["high"]),
                "low": float(x["low"]),
                "close": float(x["close"]),
                "volume": int(x["volume"]),
            })
        except Exception:
            pass

    if len(rows) < 70:
        raise ValueError("K線資料不足")

    return rows


def avg(nums):
    return sum(nums) / len(nums) if nums else 0


def calc_strategy(rows, period=60, vol_mult=1.6, atr_len=14, body_atr_mult=0.6):
    break_state = 0
    anchor = None
    last = None

    for i in range(period + atr_len, len(rows)):
        row = rows[i]
        prev = rows[i - 1]

        h1 = max(x["high"] for x in rows[i - period:i])
        vol_avg_p = avg([x["volume"] for x in rows[i - period:i]])

        tr_list = []
        for j in range(i - atr_len + 1, i + 1):
            r = rows[j]
            p = rows[j - 1]
            tr = max(
                r["high"] - r["low"],
                abs(r["high"] - p["close"]),
                abs(r["low"] - p["close"]),
            )
            tr_list.append(tr)

        atr_n = avg(tr_list)
        real_body = abs(row["close"] - row["open"])
        cond_vol = row["volume"] > vol_avg_p * vol_mult if vol_avg_p else False
        cond_break = (
            row["close"] > h1
            and row["close"] > row["open"]
            and real_body > atr_n * body_atr_mult
        )

        cdp = (prev["high"] + prev["low"] + prev["close"] * 2) / 4
        signal = 0

        if break_state == 0 and cond_break and cond_vol:
            anchor = h1
            break_state = 1

        elif break_state == 1:
            if row["close"] < cdp:
                break_state = 2
            elif cond_break and row["close"] > (anchor or 0):
                signal = 1

        last = {
            "close": row["close"],
            "open": row["open"],
            "high": row["high"],
            "volume": row["volume"],
            "h1": h1,
            "vol_avg_p": vol_avg_p,
            "cond_vol": cond_vol,
            "cond_break": cond_break,
            "cdp": cdp,
            "anchor": anchor,
            "signal": signal,
            "break_state": break_state,
        }

    return last


def analyze_stock_logic(symbol: str):
    rows = load_kbars(symbol)
    r = calc_strategy(rows)

    score = 20
    pros = []
    risks = []

    if r["signal"] == 1:
        score = 100
        pros.append("策略訊號已觸發")
    elif r["break_state"] == 1:
        score = 50
        pros.append("突破後觀察中")
    elif r["cond_break"]:
        score = 35
        pros.append("突破條件有部分符合")

    if r["cond_vol"]:
        score += 10
        pros.append("量能條件符合")

    if r["close"] > r["cdp"]:
        pros.append("收盤仍站在 CDP 之上")
    else:
        risks.append("收盤跌破 CDP")

    if not r["cond_vol"]:
        risks.append("量能尚未確認")

    score = min(score, 100)

    return {
        "symbol": symbol,
        "name": STOCK_NAMES.get(symbol, symbol),
        "close": r["close"],
        "open": r["open"],
        "high": r["high"],
        "volume": r["volume"],
        "strength": round((r["close"] - r["open"]) / r["open"], 3) if r["open"] else 0,
        "score": score,
        "signal": r["signal"],
        "break_state": r["break_state"],
        "cond_break": r["cond_break"],
        "cond_vol": r["cond_vol"],
        "anchor": r["anchor"],
        "cdp": round(r["cdp"], 3),
        "pros": pros,
        "risks": risks,
        "suggestion": "策略訊號已觸發可優先觀察" if r["signal"] == 1 else "尚未完整觸發，先觀察量價與 CDP"
    }


def make_local_ai_text(r):
    return f"""【策略狀態】
- {r["name"]}（{r["symbol"]}）分數 {r["score"]}。
- signal={r["signal"]}，break_state={r["break_state"]}。
- cond_break={r["cond_break"]}，cond_vol={r["cond_vol"]}。

【強勢原因】
- {"、".join(r["pros"]) if r["pros"] else "尚未出現完整強勢訊號。"}

【風險】
- {"、".join(r["risks"]) if r["risks"] else "目前主要風險不明顯。"}

【操作建議】
- {r["suggestion"]}
"""


def analyze_stock_with_gemini(r):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"llm_analysis": make_local_ai_text(r), "llm_model": "local-fallback"}

    client = genai.Client(api_key=api_key)

    prompt = f"""
你是台股短線策略分析助理。請使用繁體中文。

股票：{r["symbol"]} {r["name"]}
分數：{r["score"]}
signal：{r["signal"]}
break_state：{r["break_state"]}
cond_break：{r["cond_break"]}
cond_vol：{r["cond_vol"]}
close：{r["close"]}
volume：{r["volume"]}
CDP：{r["cdp"]}
anchor：{r["anchor"]}

請用以下格式輸出：
【策略狀態】
【強勢原因】
【風險】
【操作建議】
"""

    try:
        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return {"llm_analysis": res.text, "llm_model": "gemini-2.0-flash"}
    except Exception:
        return {"llm_analysis": make_local_ai_text(r), "llm_model": "local-fallback"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"ok": True, "message": "stock scanner api running"}


@app.get("/scan")
def scan():
    result = []
    for symbol in load_symbols():
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
