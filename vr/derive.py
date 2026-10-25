"""Derive (formerly Lyra) on-chain options: live instruments and tickers (mark IV, bid/ask IV,
open interest, delta). Public v3 endpoints, no key.

    python -m vr.derive book --currency BTC ETH

Endpoints (https://docs.derive.xyz, base https://api.derive.xyz/v3): POST public/get_all_instruments
(paginated) and POST public/get_tickers (one call per expiry; ticker fields are abbreviated:
option_pricing.i = mark IV as a fraction, bi/ai = bid/ask IV, d = delta, f = forward; stats.oi =
open interest; I = index price). The private/* history endpoints need a signed wallet and are not
used. Writes data/processed/derive/book_<CCY>_<date>T<hour>.csv with the same columns as the
Deribit book so the two can be joined on (expiry, strike, type).
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from vr.store import ROOT

API = "https://api.derive.xyz/v3"
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
    rows, page = [], 1
    while True:
        res = _post("public/get_all_instruments", {"currency": currency, "instrument_type": "option",
                                                   "expired": False, "page": page})
        for i in res["instruments"]:
            if not i.get("is_active"):
                continue
            od = i["option_details"]
            rows.append({"instrument_name": i["instrument_name"],
                         "expiry": pd.to_datetime(int(od["expiry"]), unit="s", utc=True),
                         "strike": float(od["strike"]), "type": "call" if od["option_type"] == "C" else "put"})
        if page >= res["pagination"]["num_pages"]:
            return pd.DataFrame(rows)
        page += 1


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def tickers(currency: str, expiry_date: str) -> pd.DataFrame:
    """All option tickers for one expiry (expiry_date as YYYYMMDD)."""
    res = _post("public/get_tickers", {"currency": currency, "instrument_type": "option", "expiry_date": expiry_date})
    rows = []
    for name, t in res["tickers"].items():
        op, st = t.get("option_pricing") or {}, t.get("stats") or {}
        rows.append({"instrument_name": name, "mark_iv": _f(op.get("i")) * 100, "bid_iv": _f(op.get("bi")) * 100,
                     "ask_iv": _f(op.get("ai")) * 100, "delta": _f(op.get("d")), "forward": _f(op.get("f")),
                     "mark_price": _f(t.get("M")), "bid_price": _f(t.get("b")), "ask_price": _f(t.get("a")),
                     "open_interest": _f(st.get("oi")), "volume": _f(st.get("v")), "underlying_price": _f(t.get("I"))})
    return pd.DataFrame(rows)


def book(currency: str) -> pd.DataFrame:
    inst = instruments(currency)
    if inst.empty:
        return inst
    now = pd.Timestamp.now(tz="UTC")
    inst["tenor_days"] = (inst["expiry"] - now).dt.total_seconds() / 86400
    days = sorted(inst["instrument_name"].str.split("-").str[1].unique())
    ticks = pd.concat([tickers(currency, d) for d in days], ignore_index=True)
    df = inst.merge(ticks, on="instrument_name", how="left").sort_values(["expiry", "strike", "type"])
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
