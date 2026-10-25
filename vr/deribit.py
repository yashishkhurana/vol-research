"""Deribit public API: the DVOL implied-volatility index (30-day constant maturity, hourly since
2021) and the live option book (mark IV, open interest, volume per instrument).

    python -m vr.deribit dvol --currency BTC ETH --start 2021-03-24
    python -m vr.deribit book --currency BTC ETH

Stores DVOL under data/raw/deribit/dvol_1h/<CCY>/<day>.parquet (columns open, high, low, close,
in vol points, e.g. 55.2 = 55.2% annualised) and the book snapshot under
data/processed/deribit/book_<CCY>_<date>T<hour>.csv. No key needed; public rate limit is generous
but the index endpoint returns at most 1,000 candles per call.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from vr.store import ROOT, append_rows

API = "https://www.deribit.com/api/v2/public"
_S = requests.Session()
DVOL_START = {"BTC": "2021-03-24", "ETH": "2021-03-24"}


def _get(path: str, **params):
    err = None
    for attempt in range(6):
        try:
            r = _S.get(f"{API}/{path}", params=params, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as e:
            err = e; time.sleep(2 ** attempt); continue
        if r.status_code == 429 or r.status_code >= 500:
            err = requests.HTTPError(f"{r.status_code} on {path}"); time.sleep(2 ** attempt); continue
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"])
        return j["result"]
    raise err


def dvol(currency: str, start: str, end: str | None = None, resolution: int = 3600) -> pd.DataFrame:
    """DVOL candles. resolution in seconds (60, 3600, 43200, 86400). Pages 1,000 candles at a time."""
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    t1 = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) if end else int(time.time() * 1000)
    step = resolution * 1000 * 1000
    rows = []
    while t0 < t1:
        res = _get("get_volatility_index_data", currency=currency, start_timestamp=t0,
                   end_timestamp=min(t1, t0 + step), resolution=str(resolution))
        data = res.get("data", [])
        rows += data
        t0 = min(t1, t0 + step)
        time.sleep(0.1)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    return df[~df.index.duplicated(keep="last")]


def book(currency: str) -> pd.DataFrame:
    """Every live option: instrument, expiry, strike, type, mark IV, mark price, OI, 24h volume,
    underlying price. One call per currency."""
    rows = _get("get_book_summary_by_currency", currency=currency, kind="option")
    df = pd.DataFrame(rows)
    parts = df["instrument_name"].str.split("-", expand=True)
    df["expiry"] = pd.to_datetime(parts[1], format="%d%b%y", utc=True) + pd.Timedelta(hours=8)
    df["strike"] = parts[2].astype(float)
    df["type"] = parts[3].map({"C": "call", "P": "put"})
    now = pd.Timestamp.now(tz="UTC")
    df["tenor_days"] = (df["expiry"] - now).dt.total_seconds() / 86400
    cols = ["instrument_name", "expiry", "tenor_days", "strike", "type", "mark_iv", "bid_price", "ask_price",
            "mark_price", "open_interest", "volume", "underlying_price"]
    df = df[[c for c in cols if c in df.columns]]
    df["snapshot_ts"] = now
    return df


def save_book(currency: str) -> Path:
    df = book(currency)
    out = ROOT / "processed" / "deribit" / f"book_{currency}_{datetime.now(timezone.utc):%Y-%m-%dT%H}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{currency}: {len(df)} options, {df.expiry.nunique()} expiries, OI {df.open_interest.sum():,.0f} contracts -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["dvol", "book"])
    ap.add_argument("--currency", nargs="+", default=["BTC", "ETH"])
    ap.add_argument("--start"); ap.add_argument("--end")
    a = ap.parse_args()
    for c in a.currency:
        if a.what == "dvol":
            df = dvol(c, a.start or DVOL_START[c], a.end)
            n = append_rows(df, "raw", "deribit", "dvol_1h", c)
            print(f"{c} DVOL: {len(df)} hourly candles -> {len(n)} day files")
        else:
            save_book(c)
