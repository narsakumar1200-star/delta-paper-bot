STRATEGY_NAME = "5-EMA Alert"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TIMEFRAMES = ["5m", "15m", "1h"]
RISK_RS = 1000.0

def check_signal(df, now_ist, symbol, tf):
    curr = df.iloc[-1]
    alert = df.iloc[-2]
    prev = df.iloc[-3]

    # SELL: Alert कैंडल पूरी तरह 5 EMA के ऊपर हो और अगली कैंडल Low तोड़े
    for cand, nxt in [(alert, curr), (prev, alert)]:
        if float(cand["low"]) > float(cand["ema5"]) and float(nxt["low"]) < float(cand["low"]):
            entry, sl = float(cand["low"]), float(cand["high"])
            risk = sl - entry
            if risk > 0 and float(curr["close"]) < sl:
                return {"side": "SELL", "entry": entry, "sl": sl, "target": entry - risk * 5.0, "rr": 5.0}

        if float(cand["high"]) < float(cand["ema5"]) and float(nxt["high"]) > float(cand["high"]):
            entry, sl = float(cand["high"]), float(cand["low"])
            risk = entry - sl
            if risk > 0 and float(curr["close"]) > sl:
                return {"side": "BUY", "entry": entry, "sl": sl, "target": entry + risk * 5.0, "rr": 5.0}
    return None
