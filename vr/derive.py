"""Derive (formerly Lyra) on-chain options: live instruments and per-instrument tickers (mark IV,
open interest, best bid/ask). Public endpoints, no key.

    python -m vr.derive book --currency BTC ETH

Endpoints (v2 API, https://docs.derive.xyz): POST /public/get_instruments, POST /public/get_ticker.
If the API has moved, the two functions below are the only things to change; the scan reads the
CSV this writes: data/processed/derive/book_<CCY>_<date>T<hour>.csv with the same columns as the
Deribit book so the two can be joined on (expiry, strike, type).
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from vr.store import ROOT

API = "https://api.lyra.finance"
_S = requests.Session()


def _post(path: str, body: dict, pause: float = 0.05):
    err = None
    for attempt in range(5):
        try:
            r = _S.post(f"{API}/{path}", json=body, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as e:
            err = e; time.sleep(2 ** attempt); continue
        if r.status_code == 429 or r.status_code >= 500:
            err = requests.HTTPError(f"{r.status_code} on {path}"); time.sleep(2 ** attempt); continue
        r.raise_for_status()
        time.sleep(pause)
        j = r.json()
        if "error" in j and j["error"]:
            raise RuntimeError(j["error"])
        return j["result"]
    raise err


def instruments(currency: str) -> pd.DataFrame:
    res = _post("public/get_instruments", {"currency": currency, "instrument_type": "option", "expired": False})
    rows = []
    for i in res:
        od = i.get("option_details", {})
        rows.append({"instrument_name": i["instrument_name"],
                     "expiry": pd.to_datetime(int(od.get("expiry", 0)), unit="s", utc=True),
                     "strike": float(od.get("strike", "nan")), "type": "call" if od.get("option_type") == "C" else "put"})
    return pd.DataFrame(rows)


def ticker(instrument_name: str) -> dict:
    t = _post("public/get_ticker", {"instrument_name": instrument_name})
    op = t.get("option_pricing", {}) or {}
    return {"instrument_name": instrument_name, "mark_iv": float(op.get("iv", "nan")) * 100,   # Derive reports iv as a fraction
            "mark_price": float(t.get("mark_price", "nan")), "bid_price": float(t.get("best_bid_price", "nan") or "nan"),
            "ask_price": float(t.get("best_ask_price", "nan") or "nan"), "open_interest": float(t.get("open_interest", "nan") or "nan"),
            "underlying_price": float(t.get("index_price", "nan") or "nan"), "delta": float(op.get("delta", "nan") or "nan")}


def book(currency: str, max_instruments: int = 400, workers: int = 8) -> pd.DataFrame:
    inst = instruments(currency)
    if inst.empty:
        return inst
    now = pd.Timestamp.now(tz="UTC")
    inst["tenor_days"] = (inst["expiry"] - now).dt.total_seconds() / 86400
    inst = inst.sort_values(["expiry", "strike"]).head(max_instruments)
    with ThreadPoolExecutor(workers) as ex:
        ticks = list(ex.map(ticker, inst["instrument_name"]))
    df = inst.merge(pd.DataFrame(ticks), on="instrument_name", how="left")
    df["snapshot_ts"] = now
    return df


def save_book(currency: str) -> Path:
    df = book(currency)
    out = ROOT / "processed" / "derive" / f"book_{currency}_{datetime.now(timezone.utc):%Y-%m-%dT%H}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{currency}: {len(df)} options, {df.expiry.nunique() if len(df) else 0} expiries -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["book"])
    ap.add_argument("--currency", nargs="+", default=["BTC", "ETH"])
    a = ap.parse_args()
    for c in a.currency:
        save_book(c)
