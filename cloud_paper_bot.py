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
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    data = {"balance": 100000.0, "open_trades": {}, "total_trades": 0, "wins": 0, "losses": 0}
    save_wallet(data)
    return data

def save_wallet(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def log_trade(row):
    df = pd.DataFrame([row])
    header = not os.path.exists(LOG_FILE)
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)

def fetch_candles(symbol, resolution, sec):
    end = int(time.time())
    start = end - (sec * 60)
    url = f"{BASE_URL}/v2/history/candles?resolution={resolution}&symbol={symbol}&start={start}&end={end}"
    r = requests.get(url, timeout=15).json()
    if not r.get("success") or not r.get("result"):
        return None
    df = pd.DataFrame(r["result"]).sort_values("time").reset_index(drop=True)
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    return df

wallet = load_wallet()
now_str = datetime.now(IST).strftime("%d-%b %I:%M %p IST")
print(f"[{now_str}] Cloud Scan Running | Balance: Rs.{wallet['balance']:.2f}")

for sym in SYMBOLS:
    for tf, sec in TIMEFRAMES.items():
        key = f"{sym}_{tf}"
        df = fetch_candles(sym, tf, sec)
        if df is None or len(df) < 10:
            continue

        curr = df.iloc[-1]
        alert = df.iloc[-2]

        if key in wallet["open_trades"]:
            t = wallet["open_trades"][key]
            hit, pnl = None, 0.0
            if t["side"] == "SELL":
                if float(curr["high"]) >= t["sl"]:
                    hit, pnl = "SL HIT ❌", -RISK_PER_TRADE
                elif float(curr["low"]) <= t["target"]:
                    hit, pnl = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO
            else:
                if float(curr["low"]) <= t["sl"]:
                    hit, pnl = "SL HIT ❌", -RISK_PER_TRADE
                elif float(curr["high"]) >= t["target"]:
                    hit, pnl = "TARGET HIT 🎯", RISK_PER_TRADE * RR_RATIO

            if hit:
                wallet["balance"] += pnl
                wallet["total_trades"] += 1
                if pnl > 0: wallet["wins"] += 1
                else: wallet["losses"] += 1
                del wallet["open_trades"][key]
                save_wallet(wallet)
                log_trade({
                    "Exit_Time": now_str, "Symbol": sym, "TF": tf, "Side": t["side"],
                    "Entry": t["entry"], "SL": t["sl"], "Target": t["target"],
                    "Status": hit, "PnL_Rs": pnl, "Balance_Rs": round(wallet["balance"], 2)
                })
                send_tg(
                    f"<b>{hit} — {key} ({t['side']})</b>\n"
                    f"Entry: {t['entry']} | SL: {t['sl']} | TGT: {t['target']}\n"
                    f"Trade P&L: <b>₹{pnl:+.0f}</b>\n"
                    f"Virtual Balance: <b>₹{wallet['balance']:,.2f}</b>\n"
                    f"Record: {wallet['wins']}W / {wallet['losses']}L | {now_str}"
                )
            continue

        if float(alert["low"]) > float(alert["ema5"]) and float(curr["low"]) < float(alert["low"]):
            entry, sl = float(alert["low"]), float(alert["high"])
            risk = sl - entry
            if risk > 0:
                target = round(entry - (risk * RR_RATIO), 2)
                wallet["open_trades"][key] = {"side": "SELL", "entry": entry, "sl": sl, "target": target, "time": now_str}
                save_wallet(wallet)
                send_tg(
                    f"🔴 <b>NEW PAPER SELL — {key}</b>\n"
                    f"Entry: <b>{entry}</b>\n"
                    f"Stop-Loss: <b>{sl}</b>\n"
                    f"Target (1:5): <b>{target}</b>\n"
                    f"Balance: ₹{wallet['balance']:,.2f} | {now_str}"
                )

        elif float(alert["high"]) < float(alert["ema5"]) and float(curr["high"]) > float(alert["high"]):
            entry, sl = float(alert["high"]), float(alert["low"])
            risk = entry - sl
            if risk > 0:
                target = round(entry + (risk * RR_RATIO), 2)
                wallet["open_trades"][key] = {"side": "BUY", "entry": entry, "sl": sl, "target": target, "time": now_str}
                save_wallet(wallet)
                send_tg(
                    f"🟢 <b>NEW PAPER BUY — {key}</b>\n"
                    f"Entry: <b>{entry}</b>\n"
                    f"Stop-Loss: <b>{sl}</b>\n"
                    f"Target (1:5): <b>{target}</b>\n"
                    f"Balance: ₹{wallet['balance']:,.2f} | {now_str}"
                )
