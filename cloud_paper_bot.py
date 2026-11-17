import os, json, time, requests
import pandas as pd
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600}
RR_RATIO = 5.0
RISK_PER_TRADE = 1000.0
STATE_FILE = "paper_wallet.json"
LOG_FILE = "paper_trades_log.csv"

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
IST = timezone(timedelta(hours=5, minutes=30))

# फिक्स शुरुआती समय: 15 नवंबर 2026 सुबह 10:00 AM IST
START_FROM_TS = int(datetime(2026, 11, 15, 10, 0, 0, tzinfo=IST).timestamp())
RULE_VERSION = "v2_sell5_buy15_nov15"

def fmt_ist(ts):
    return datetime.fromtimestamp(int(ts), tz=IST).strftime("%d-%b %I:%M %p IST")

def send_tg(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print("TG Error:", e)

def load_wallet():
    if os.path.exists(STATE_FILE) and os.path.getsize(STATE_FILE) > 0:
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if data.get("rule_version") == RULE_VERSION:
                    return data
        except Exception:
            pass
    # नए नियम के साथ 15 नवंबर सुबह 10:00 AM से फ्रेश रीसेट
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    return {
        "rule_version": RULE_VERSION,
        "balance": 100000.0,
        "open_trades": {},
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "last_checked_ts": START_FROM_TS
    }

def save_wallet(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def log_trade(row):
    df = pd.DataFrame([row])
    header = not os.path.exists(LOG_FILE)
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)

def fetch_candles(symbol, resolution, sec, since_ts):
    end = int(time.time())
    start = min(since_ts - (sec * 40), end - (sec * 300))
    url = f"{BASE_URL}/v2/history/candles?resolution={resolution}&symbol={symbol}&start={start}&end={end}"
    r = requests.get(url, timeout=15).json()
    if not r.get("success") or not r.get("result"):
        return None
    df = pd.DataFrame(r["result"]).sort_values("time").reset_index(drop=True)
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema15"] = df["close"].ewm(span=15, adjust=False).mean()
    return df

wallet = load_wallet()
last_ts = max(int(wallet.get("last_checked_ts", START_FROM_TS)), START_FROM_TS)
now_ts = int(time.time())
now_str = fmt_ist(now_ts)
wallet["last_checked"] = now_str

for sym in SYMBOLS:
    for tf, sec in TIMEFRAMES.items():
        key = f"EMA-5/15|{sym}_{tf}"
        df = fetch_candles(sym, tf, sec, last_ts)
        if df is None or len(df) < 20:
            continue

        # 1. खुले ट्रेड को चेक करें
        if key in wallet["open_trades"]:
            t = wallet["open_trades"][key]
            entry_ts = int(t.get("entry_ts", last_ts))
            active_df = df[df["time"] >= entry_ts]
            hit, pnl, hit_time = None, 0.0, now_str

            for _, row in active_df.iterrows():
                if t["side"] == "SELL":
                    if float(row["high"]) >= t["sl"]:
                        hit, pnl, hit_time = "SL HIT ❌", -RISK_PER_TRADE, fmt_ist(row["time"])
                        break
                    elif float(row["low"]) <= t["target"]:
                        hit, pnl, hit_time = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO, fmt_ist(row["time"])
                        break
                else:
                    if float(row["low"]) <= t["sl"]:
                        hit, pnl, hit_time = "SL HIT ❌", -RISK_PER_TRADE, fmt_ist(row["time"])
                        break
                    elif float(row["high"]) >= t["target"]:
                        hit, pnl, hit_time = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO, fmt_ist(row["time"])
                        break

            if hit:
                wallet["balance"] += pnl
                wallet["total_trades"] += 1
                if pnl > 0: wallet["wins"] += 1
                else: wallet["losses"] += 1
                del wallet["open_trades"][key]
                log_trade({
                    "Exit_Time": hit_time, "Strategy": "SELL-5EMA / BUY-15EMA", "Symbol": sym, "TF": tf,
                    "Side": t["side"], "Entry": t["entry"], "SL": t["sl"], "Target": t["target"],
                    "Status": hit, "PnL_Rs": pnl, "Balance_Rs": round(wallet["balance"], 2)
                })
                send_tg(
                    f"<b>{hit} — {sym} ({tf})</b>\n"
                    f"Side: {t['side']} | Entry: {t['entry']}\n"
                    f"SL: {t['sl']} | Target: {t['target']}\n"
                    f"Exit: {hit_time} | P&L: <b>₹{pnl:+.0f}</b>\n"
                    f"Balance: <b>₹{wallet['balance']:,.2f}</b>"
                )
            else:
                continue

        # 2. 15 नवंबर 10:00 AM से आगे की कैंडल्स स्कैन करें (SELL: 5 EMA | BUY: 15 EMA)
        for idx in range(15, len(df)):
            if key in wallet["open_trades"]:
                break
            brk = df.iloc[idx]
            brk_ts = int(brk["time"])
            if brk_ts < last_ts or brk_ts < START_FROM_TS:
                continue

            alert = df.iloc[idx - 1]
            side, entry, sl, target = None, 0.0, 0.0, 0.0

            # SELL केवल 5 EMA पर
            if float(alert["low"]) > float(alert["ema5"]) and float(brk["low"]) < float(alert["low"]):
                entry, sl = float(alert["low"]), float(alert["high"])
                risk = sl - entry
                if risk > 0:
                    side, target = "SELL", round(entry - (risk * RR_RATIO), 2)

            # BUY केवल 15 EMA पर (5 EMA पर कभी नहीं)
            elif float(alert["high"]) < float(alert["ema15"]) and float(brk["high"]) > float(alert["high"]):
                entry, sl = float(alert["high"]), float(alert["low"])
                risk = entry - sl
                if risk > 0:
                    side, target = "BUY", round(entry + (risk * RR_RATIO), 2)

            if side:
                brk_time_str = fmt_ist(brk_ts)
                future_df = df.iloc[idx:]
                closed_status, closed_pnl, exit_time_str = None, 0.0, None

                for _, frow in future_df.iterrows():
                    if side == "SELL":
                        if float(frow["high"]) >= sl:
                            closed_status, closed_pnl, exit_time_str = "SL HIT ❌", -RISK_PER_TRADE, fmt_ist(frow["time"])
                            break
                        elif float(frow["low"]) <= target:
                            closed_status, closed_pnl, exit_time_str = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO, fmt_ist(frow["time"])
                            break
                    else:
                        if float(frow["low"]) <= sl:
                            closed_status, closed_pnl, exit_time_str = "SL HIT ❌", -RISK_PER_TRADE, fmt_ist(frow["time"])
                            break
                        elif float(frow["high"]) >= target:
                            closed_status, closed_pnl, exit_time_str = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO, fmt_ist(frow["time"])
                            break

                if closed_status:
                    wallet["balance"] += closed_pnl
                    wallet["total_trades"] += 1
                    if closed_pnl > 0: wallet["wins"] += 1
                    else: wallet["losses"] += 1
                    log_trade({
                        "Exit_Time": exit_time_str, "Strategy": "SELL-5EMA / BUY-15EMA", "Symbol": sym, "TF": tf,
                        "Side": side, "Entry": round(entry, 2), "SL": round(sl, 2), "Target": target,
                        "Status": closed_status, "PnL_Rs": closed_pnl, "Balance_Rs": round(wallet["balance"], 2)
                    })
                else:
                    wallet["open_trades"][key] = {
                        "strategy": "SELL-5EMA / BUY-15EMA", "side": side,
                        "entry": round(entry, 2), "sl": round(sl, 2), "target": target,
                        "risk_rs": RISK_PER_TRADE, "reward_rs": RISK_PER_TRADE * RR_RATIO,
                        "time": brk_time_str, "entry_ts": brk_ts
                    }
                    icon = "🔴 (5 EMA)" if side == "SELL" else "🟢 (15 EMA)"
                    send_tg(
                        f"{icon} <b>LIVE OPEN — {sym} ({tf})</b>\n"
                        f"Side: <b>{side}</b> | Entry: <b>{round(entry, 2)}</b>\n"
                        f"SL: <b>{round(sl, 2)}</b> | Target (1:5): <b>{target}</b>\n"
                        f"Entry Time: {brk_time_str}"
                    )

wallet["last_checked_ts"] = now_ts - 300
save_wallet(wallet)
