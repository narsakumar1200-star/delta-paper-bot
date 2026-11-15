import os, json, time, glob, importlib.util, requests
import pandas as pd
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.india.delta.exchange"
STATE_FILE = "paper_wallet.json"
LOG_FILE = "paper_trades_log.csv"
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
IST = timezone(timedelta(hours=5, minutes=30))

TF_SEC = {"5m": 300, "15m": 900, "1h": 3600}

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
    return {"balance": 100000.0, "open_trades": {}, "total_trades": 0, "wins": 0, "losses": 0}

def save_wallet(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def log_trade(row):
    df = pd.DataFrame([row])
    header = not os.path.exists(LOG_FILE)
    df.to_csv(LOG_FILE, mode="a", header=header, index=False)

candle_cache = {}
def get_candles(symbol, tf):
    cache_key = f"{symbol}_{tf}"
    if cache_key in candle_cache:
        return candle_cache[cache_key]
    sec = TF_SEC.get(tf, 900)
    end = int(time.time())
    start = end - (sec * 250) # 200 EMA के लिए 250 कैंडल्स
    url = f"{BASE_URL}/v2/history/candles?resolution={tf}&symbol={symbol}&start={start}&end={end}"
    r = requests.get(url, timeout=15).json()
    if not r.get("success") or not r.get("result"):
        return None
    df = pd.DataFrame(r["result"]).sort_values("time").reset_index(drop=True)
    df["ema5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    candle_cache[cache_key] = df
    return df

def load_strategies():
    strats = []
    for path in sorted(glob.glob("strategies/*.py")):
        name = os.path.basename(path)[:-3]
        if name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "check_signal"):
            strats.append(mod)
    return strats

wallet = load_wallet()
now_ist = datetime.now(IST)
now_str = now_ist.strftime("%d-%b %I:%M %p IST")
wallet["last_checked"] = now_str

strategies = load_strategies()
wallet["active_strategies"] = [getattr(s, "STRATEGY_NAME", s.__name__) for s in strategies]

for mod in strategies:
    s_name = getattr(mod, "STRATEGY_NAME", mod.__name__)
    symbols = getattr(mod, "SYMBOLS", ["BTCUSD", "ETHUSD"])
    timeframes = getattr(mod, "TIMEFRAMES", ["15m"])
    risk_rs = float(getattr(mod, "RISK_RS", 1000.0))

    for sym in symbols:
        for tf in timeframes:
            df = get_candles(sym, tf)
            if df is None or len(df) < 20:
                continue

            trade_key = f"{s_name}|{sym}_{tf}"
            curr = df.iloc[-1]

            # 1. खुले हुए ट्रेड का SL या Target चेक करें
            if trade_key in wallet["open_trades"]:
                t = wallet["open_trades"][trade_key]
                hit, pnl = None, 0.0
                if t["side"] == "SELL":
                    if float(curr["high"]) >= t["sl"]:
                        hit, pnl = "SL HIT ❌", -t["risk_rs"]
                    elif float(curr["low"]) <= t["target"]:
                        hit, pnl = "TARGET HIT 🎯", t["reward_rs"]
                else:
                    if float(curr["low"]) <= t["sl"]:
                        hit, pnl = "SL HIT ❌", -t["risk_rs"]
                    elif float(curr["high"]) >= t["target"]:
                        hit, pnl = "TARGET HIT 🎯", t["reward_rs"]

                if hit:
                    wallet["balance"] += pnl
                    wallet["total_trades"] += 1
                    if pnl > 0: wallet["wins"] += 1
                    else: wallet["losses"] += 1
                    del wallet["open_trades"][trade_key]
                    log_trade({
                        "Exit_Time": now_str, "Strategy": s_name, "Symbol": sym, "TF": tf,
                        "Side": t["side"], "Entry": t["entry"], "SL": t["sl"], "Target": t["target"],
                        "Status": hit, "PnL_Rs": pnl, "Balance_Rs": round(wallet["balance"], 2)
                    })
                    send_tg(
                        f"<b>{hit} [{s_name}]</b>\n"
                        f"{sym} ({tf}) — {t['side']}\n"
                        f"Entry: {t['entry']} | SL: {t['sl']} | TGT: {t['target']}\n"
                        f"P&L: <b>₹{pnl:+.0f}</b> | Balance: <b>₹{wallet['balance']:,.2f}</b>"
                    )
                continue

            # 2. स्ट्रैटेजी फाइल से नया सिग्नल पूछें
            sig = mod.check_signal(df, now_ist, sym, tf)
            if sig and sig.get("side") in ("BUY", "SELL"):
                rr = float(sig.get("rr", 5.0))
                wallet["open_trades"][trade_key] = {
                    "strategy": s_name, "side": sig["side"],
                    "entry": round(float(sig["entry"]), 2),
                    "sl": round(float(sig["sl"]), 2),
                    "target": round(float(sig["target"]), 2),
                    "risk_rs": risk_rs, "reward_rs": risk_rs * rr,
                    "time": now_str
                }
                icon = "🔴" if sig["side"] == "SELL" else "🟢"
                send_tg(
                    f"{icon} <b>NEW {sig['side']} [{s_name}]</b>\n"
                    f"Market: <b>{sym} ({tf})</b>\n"
                    f"Entry: <b>{sig['entry']}</b> | SL: <b>{sig['sl']}</b> | TGT: <b>{sig['target']}</b>\n"
                    f"Time: {now_str}"
                )

save_wallet(wallet)
