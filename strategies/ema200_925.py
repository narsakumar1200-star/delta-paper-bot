STRATEGY_NAME = "9:25-200EMA"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TIMEFRAMES = ["15m"]
RISK_RS = 1000.0

def check_signal(df, now_ist, symbol, tf):
    # सुबह 9:20 से 9:45 IST के बीच का सेशन या 200 EMA ट्रेंड पुलबैक
    in_morning_window = (now_ist.hour == 9 and 20 <= now_ist.minute <= 45)
    if not in_morning_window:
        return None

    curr = df.iloc[-1]
    alert = df.iloc[-2]
    close_p = float(alert["close"])
    ema200 = float(alert["ema200"])

    # 200 EMA के ऊपर हो तो केवल BUY, नीचे हो तो केवल SELL (1:3 RR)
    if close_p > ema200 and float(curr["high"]) > float(alert["high"]):
        entry, sl = float(alert["high"]), float(alert["low"])
        risk = entry - sl
        if risk > 0:
            return {"side": "BUY", "entry": entry, "sl": sl, "target": entry + risk * 3.0, "rr": 3.0}

    elif close_p < ema200 and float(curr["low"]) < float(alert["low"]):
        entry, sl = float(alert["low"]), float(alert["high"])
        risk = sl - entry
        if risk > 0:
            return {"side": "SELL", "entry": entry, "sl": sl, "target": entry - risk * 3.0, "rr": 3.0}

    return None
