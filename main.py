from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import yfinance as yf
import os
from google import genai

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


def breakout_retest_strategy(
    df,
    period=60,
    vol_mult=1.6,
    atr_len=14,
    body_atr_mult=0.6
):
    df = df.copy()

    df["h1"] = df["high"].shift(1).rolling(period).max()
    df["vol_avg_p"] = df["volume"].rolling(period).mean()
    df["cond_vol"] = df["volume"] > vol_mult * df["vol_avg_p"]

    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["true_range"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    df["atr_n"] = df["true_range"].rolling(atr_len).mean()
    df["real_body"] = (df["close"] - df["open"]).abs()

    df["cond_break"] = (df["close"] > df["open"]) & (
        df["real_body"] > body_atr_mult * df["atr_n"]
    )

    df["cdp"] = (
        df["high"].shift(1)
        + df["low"].shift(1)
        + 2 * df["close"].shift(1)
    ) / 4

    df["anchor"] = None
    df["signal"] = 0
    df["break_state"] = 0

    break_state = 0
    anchor = None

    for i in range(len(df)):
        row = df.iloc[i]

        if (
            pd.isna(row["h1"])
            or pd.isna(row["vol_avg_p"])
            or pd.isna(row["atr_n"])
            or pd.isna(row["cdp"])
        ):
            df.at[df.index[i], "anchor"] = anchor
            df.at[df.index[i], "break_state"] = break_state
            continue

        if break_state == 0:
            if (
                row["close"] > row["h1"]
                and row["close"] > row["cdp"]
                and row["cond_vol"]
                and row["cond_break"]
            ):
                anchor = row["h1"]
                break_state = 1

        elif break_state == 1:
            if (
                row["low"] <= anchor
                and row["close"] > anchor
                and row["close"] > row["cdp"]
            ):
                df.at[df.index[i], "signal"] = 1
                break_state = 2

        df.at[df.index[i], "anchor"] = anchor
        df.at[df.index[i], "break_state"] = break_state

    return df

def get_price_data(symbol: str):
    symbols_to_try = [
        f"{symbol}.TW",
        f"{symbol}.TWO"
    ]

    df = pd.DataFrame()

    for s in symbols_to_try:
        try:
            print(f"Trying {s}")
            df = yf.download(
                s,
                period="6mo",
                interval="1d",
                auto_adjust=False,
                progress=False
            )
            if not df.empty:
                print(f"SUCCESS: {s}")
                break
        except Exception as e:
            print(f"FAIL: {s} -> {e}")

    if df.empty:
        raise ValueError(f"無法下載 {symbol} 的股價資料")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })

    needed_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in needed_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{symbol} 缺少欄位: {missing}")

    df = df[needed_cols].copy()

    for col in needed_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna().reset_index(drop=True)
    return df



def calc_score(close, anchor, volume, break_state, signal):
    breakout_strength = 0.0
    if anchor is not None and anchor != 0:
        breakout_strength = (close - anchor) / anchor

    volume_score = volume / 1_000_000

    if signal == 1:
        signal_bonus = 1.0
    elif break_state == 1:
        signal_bonus = 0.5
    else:
        signal_bonus = 0.0

    price_position = 1.0 if (anchor is not None and close > anchor) else 0.0

    score = (
        breakout_strength * 50
        + volume_score * 0.2
        + signal_bonus * 20
        + price_position * 10
    )

    return round(score, 3), breakout_strength


def build_stock_result(symbol: str, last_row):
    anchor = float(last_row["anchor"]) if pd.notna(last_row["anchor"]) else None
    close = float(last_row["close"])
    volume = int(last_row["volume"])
    break_state = int(last_row["break_state"])
    signal = int(last_row["signal"])

    score, breakout_strength = calc_score(
        close=close,
        anchor=anchor,
        volume=volume,
        break_state=break_state,
        signal=signal
    )

    return {
        "symbol": symbol,
        "close": close,
        "volume": volume,
        "anchor": anchor,
        "break_state": break_state,
        "signal": signal,
        "strength": round(breakout_strength, 3),
        "score": score,
        "reason": "已完成回踩訊號" if signal == 1 else "已突破，等待回踩"
    }


def run_post_market_scan():
    symbols = load_symbols()
    matched = []

    for idx, symbol in enumerate(symbols, start=1):
        try:
            print(f"[{idx}/{len(symbols)}] scanning {symbol}")

            df = get_price_data(symbol)
            result_df = breakout_retest_strategy(df)
            last_row = result_df.iloc[-1]

            if int(last_row["break_state"]) in [1, 2]:
                matched.append(build_stock_result(symbol, last_row))

        except Exception as e:
            print(f"error: {symbol} - {e}")

    matched = sorted(
        matched,
        key=lambda x: (x["score"], x["signal"], x["volume"]),
        reverse=True
    )

    return matched


def analyze_stock_logic(symbol: str):
    if not str(symbol).isdigit():
        return {
            "symbol": symbol,
            "error": "symbol 格式錯誤，請輸入股票代號"
        }

    df = get_price_data(symbol)
    result_df = breakout_retest_strategy(df)
    last_row = result_df.iloc[-1]

    close = float(last_row["close"])
    anchor = float(last_row["anchor"]) if pd.notna(last_row["anchor"]) else None
    volume = int(last_row["volume"])
    break_state = int(last_row["break_state"])
    signal = int(last_row["signal"])

    score, breakout_strength = calc_score(
        close=close,
        anchor=anchor,
        volume=volume,
        break_state=break_state,
        signal=signal
    )

    if signal == 1:
        stage_text = "已完成回踩訊號"
    elif break_state == 1:
        stage_text = "已突破，等待回踩"
    else:
        stage_text = "目前未進入有效 Breakout Retest 階段"

    pros = []
    risks = []

    if break_state >= 1:
        pros.append("股價已突破前高區")
    if signal == 1:
        pros.append("回踩後仍站回 anchor 之上")
    if anchor is not None and close > anchor:
        pros.append("目前價格仍高於 anchor")
    if volume > 0:
        pros.append("近期有量能資料可供追蹤")

    if break_state == 1 and signal == 0:
        risks.append("尚未完成回踩確認，可能是假突破")
    if breakout_strength < 0.02:
        risks.append("突破幅度不大，後續容易震盪")
    if anchor is None:
        risks.append("目前尚無明確 anchor 可追蹤")

    if signal == 1:
        suggestion = "偏強，可列入優先觀察名單，後續觀察是否續量上攻。"
    elif break_state == 1:
        suggestion = "先觀察回踩是否守住 anchor，再考慮後續動作。"
    else:
        suggestion = "目前不屬於此策略的有效候選股。"

    return {
        "symbol": symbol,
        "close": close,
        "anchor": anchor,
        "volume": volume,
        "break_state": break_state,
        "signal": signal,
        "strength": round(breakout_strength, 3),
        "score": score,
        "stage": stage_text,
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
價格：{rule_result["close"]}
score：{rule_result["score"]}
strength：{rule_result["strength"]}
狀態：{rule_result["stage"]}

優點：
{chr(10).join(rule_result["pros"])}

風險：
{chr(10).join(rule_result["risks"])}

請用繁體中文、簡單白話回答：
1. 這檔在強什麼
2. 有沒有風險
3. 建議現在怎麼做

請簡潔、像真的分析師，不要太空泛。
"""

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt
    )

    return {"llm_analysis": response.text}


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
