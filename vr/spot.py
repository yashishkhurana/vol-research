"""Hourly spot closes from Binance for realised volatility. Public REST, no key.

    python -m vr.spot --symbol BTCUSDT ETHUSDT --start 2021-01-01

Stored under data/raw/binance/klines_1h/<SYMBOL>/<day>.parquet; `load_close` reads it back.
"""
from __future__ import annotations

import argparse
import time

import pandas as pd
import requests

from vr.store import append_rows, read_range

API = "https://api.binance.com/api/v3/klines"
_S = requests.Session()


def klines_1h(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) if end else int(time.time() * 1000)
    out = []
    while t0 < t1:
        for attempt in range(6):
            try:
                r = _S.get(API, params=dict(symbol=symbol, interval="1h", startTime=t0, endTime=t1, limit=1000), timeout=30)
                if r.status_code in (418, 429) or r.status_code >= 500:
                    time.sleep(2 ** attempt); continue
                r.raise_for_status(); rows = r.json(); break
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"gave up on {symbol} at {t0}")
        if not rows:
            break
        out += rows
        t0 = rows[-1][0] + 3_600_000
        time.sleep(0.05)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_close(symbol: str, start: str, end: str) -> pd.Series:
    df = read_range("raw", "binance", "klines_1h", symbol, start, end)
    return df["close"] if not df.empty else pd.Series(dtype=float)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    ap.add_argument("--start", default="2021-01-01"); ap.add_argument("--end")
    a = ap.parse_args()
    for s in a.symbol:
        df = klines_1h(s, a.start, a.end)
        n = append_rows(df, "raw", "binance", "klines_1h", s)
        print(f"{s}: {len(df)} hourly bars -> {len(n)} day files")
