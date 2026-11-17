import os, json, time, requests
import pandas as pd
from datetime import datetime, timezone, timedelta

BASE_URL = "https://api.india.delta.exchange"
SYMBOLS = ["BTCUSD", "ETHUSD"]
TIMEFRAMES = {
    "5m":  {"sec": 300,  "count": 850},
    "15m": {"sec": 900,  "count": 400},
    "1h":  {"sec": 3600, "count": 200}
}
RR_RATIO = 5.0
RISK_PER_TRADE = 1000.0
STATE_FILE = "paper_wallet.json"
LOG_FILE = "paper_trades_log.csv"

TG_TOKEN = os.environ
