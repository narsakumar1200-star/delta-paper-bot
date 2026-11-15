STRATEGY_NAME = "5-EMA Alert"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TIMEFRAMES = ["5m", "15m", "1h"]
RISK_RS = 1000.0
RR_RATIO = 5.0

def check_signal(df, now_ist, symbol, tf):
    # पिछली 4 कैंडल्स तक पीछे चेक करें ताकि 5-15 मिनट की देरी होने पर भी असली एंट्री पॉइंट न छूटे
    lookback = 4 if tf == "5m" else (3 if tf == "15m" else 2)
    total = len(df)
    if total < lookback + 3:
        return None

    # सबसे ताज़ा से पीछे की तरफ चेक करें
    for offset in range(1, lookback + 1):
        alert_idx = total - 1 - offset
        break_idx = alert_idx + 1

        alert = df.iloc[alert_idx]
        brk = df.iloc[break_idx]

        # 1. SELL सिग्नल: Alert कैंडल पूरी तरह 5 EMA के ऊपर हो, और अगली कैंडल उसका Low तोड़े
        if float(alert["low"]) > float(alert["ema5"]) and float(brk["low"]) < float(alert["low"]):
            entry = float(alert["low"])
            sl = float(alert["high"])
            risk = sl - entry
            if risk <= 0:
                continue
            target = entry - (risk * RR_RATIO)

            # चेक करें कि ब्रेकआउट के बाद से अभी तक SL या Target हिट तो नहीं हो गया
            subsequent = df.iloc[break_idx:]
            if float(subsequent["high"].max()) >= sl or float(subsequent["low"].min()) <= target:
                continue

            return {
                "side": "SELL",
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "target": round(target, 2),
                "rr": RR_RATIO
            }

        # 2. BUY सिग्नल: Alert कैंडल पूरी तरह 5 EMA के नीचे हो, और अगली कैंडल उसका High तोड़े
        if float(alert["high"]) < float(alert["ema5"]) and float(brk["high"]) > float(alert["high"]):
            entry = float(alert["high"])
            sl = float(alert["low"])
            risk = entry - sl
            if risk <= 0:
                continue
            target = entry + (risk * RR_RATIO)

            # चेक करें कि ब्रेकआउट के बाद से अभी तक SL या Target हिट तो नहीं हो गया
            subsequent = df.iloc[break_idx:]
            if float(subsequent["low"].min()) <= sl or float(subsequent["high"].max()) >= target:
                continue

            return {
                "side": "BUY",
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "target": round(target, 2),
                "rr": RR_RATIO
            }

    return None
