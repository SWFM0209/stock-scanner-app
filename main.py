from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
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
    tw_symbol = f"{symbol}.TW"
    otc_symbol = f"{symbol}.TWO"

    df = yf.download(
        tw_symbol,
        period="8mo",
        interval="1d",
        auto_adjust=False,
        progress=False
    )

    if df.empty:
        df = yf.download(
            otc_symbol,
            period="8mo",
            interval="1d",
            auto_adjust=False,
            progress=False
        )

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


def build_stock_result(symbol: str, last_row):
    anchor = float(last_row["anchor"]) if pd.notna(last_row["anchor"]) else None
    close = float(last_row["close"])
    volume = int(last_row["volume"])
    break_state = int(last_row["break_state"])
    signal = int(last_row["signal"])

    strength = None
    if anchor and anchor != 0:
        strength = float((close - anchor) / anchor)

    return {
        "symbol": symbol,
        "close": close,
        "volume": volume,
        "anchor": anchor,
        "break_state": break_state,
        "signal": signal,
        "strength": strength,
        "reason": "已突破，等待回踩" if break_state == 1 else "已完成回踩訊號"
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

            # 先抓已突破待回踩 + 已完成訊號
            if int(last_row["break_state"]) in [1, 2]:
                matched.append(build_stock_result(symbol, last_row))

        except Exception as e:
            print(f"error: {symbol} - {e}")

    matched = sorted(
        matched,
        key=lambda x: (
            x["signal"],
            x["strength"] if x["strength"] is not None else -999,
            x["volume"]
        ),
        reverse=True
    )

    return matched


def analyze_stock_logic(symbol: str):
    df = get_price_data(symbol)
    result_df = breakout_retest_strategy(df)
    last_row = result_df.iloc[-1]

    close = float(last_row["close"])
    anchor = float(last_row["anchor"]) if pd.notna(last_row["anchor"]) else None
    break_state = int(last_row["break_state"])
    signal = int(last_row["signal"])
    volume = int(last_row["volume"])

    strength = None
    if anchor and anchor != 0:
        strength = float((close - anchor) / anchor)

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
    if strength is not None and strength > 0:
        pros.append("目前收盤仍高於 anchor")
    if volume > 0:
        pros.append("近期有量能資料可供追蹤")

    if break_state == 1 and signal == 0:
        risks.append("尚未完成回踩確認，可能是假突破")
    if strength is not None and strength < 0.02:
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
        "strength": strength,
        "stage": stage_text,
        "pros": pros,
        "risks": risks,
        "suggestion": suggestion
    }


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
    return analyze_stock_logic(req.symbol)
