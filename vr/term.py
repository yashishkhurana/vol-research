"""Implied-vol term structure from daily Deribit option prices.

Input: CryptoDataDownload's per-expiry files (data/raw/cdd/deribit_options/*.zip), one row per
option per UTC day: open, high, low, close in coin units (BTC or ETH), volume. Deribit options are
inverse: a price of 0.05 BTC is worth 0.05 x the forward in USD. So with a forward F for the
expiry, USD price = close x F and the implied vol is Black-76 with zero rates.

Forward: Deribit's own dated future for that expiry when one exists that day; otherwise the
perpetual close times exp(basis x T), with the annualised basis interpolated across that day's
futures by tenor (flat beyond the ends).

Pipeline per day: options that traded (volume > 0), 2 days or more to expiry, |delta| in 0.2-0.8
-> ATM IV per expiry by interpolating IV in log-moneyness at k = 0 (needs a strike on each side)
-> constant-maturity ATM IV at 30/90/180/365 days by interpolating total variance (IV^2 x T)
linearly in T between the two expiries that bracket the target. No extrapolation: a tenor with
no expiry beyond it that day is missing.
"""
from __future__ import annotations

import glob
import io
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.stats import norm

from vr.store import ROOT

CDD_DIR = ROOT / "raw" / "cdd" / "deribit_options"
API = "https://www.deribit.com/api/v2/public"
EXPIRY_HOUR = 8                                   # Deribit expiries settle at 08:00 UTC
# Deribit (and so CDD) daily candles run 08:00 to 08:00 UTC: the close of "date" d is at d+1 08:00.
CLOSE_OFFSET = pd.Timedelta(hours=32)
_S = requests.Session()


# ---------- option prices ----------

def load_options(ccy: str, start: str = "2023-01-01") -> pd.DataFrame:
    """Every option-day for one currency from the CDD zips, traded rows only."""
    frames = []
    for f in sorted(glob.glob(str(CDD_DIR / f"DeriBit_{ccy}_*_allStrikes_aggregated.zip"))):
        with zipfile.ZipFile(f) as z:
            df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
        frames.append(df[df["volume"] > 0])
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    exp = pd.to_datetime(df["instrument_name"].str.split("-").str[1], format="%d%b%y", utc=True)
    df["expiry"] = exp + pd.Timedelta(hours=EXPIRY_HOUR)
    df["asof"] = df["date"] + CLOSE_OFFSET
    df["T"] = (df["expiry"] - df["asof"]).dt.total_seconds() / (365 * 86400)
    df["is_call"] = df["option_type"].eq("C")
    return df[(df["date"] >= pd.Timestamp(start, tz="UTC")) & (df["T"] >= 2 / 365)].reset_index(drop=True)


# ---------- futures and forwards ----------

def _get(path: str, **params):
    for attempt in range(6):
        try:
            r = _S.get(f"{API}/{path}", params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt); continue
            r.raise_for_status()
            return r.json()["result"]
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(2 ** attempt)
    raise RuntimeError(f"gave up on {path} {params}")


def futures_list(ccy: str, since: str = "2023-01-01") -> pd.DataFrame:
    """Candidate dated futures: one per option expiry that falls on a Friday (Deribit lists weekly,
    monthly and quarterly futures on Fridays; daily option expiries have none), plus the perpetual.
    get_instruments(expired=true) only returns recent expiries, so names come from the option files."""
    mats = sorted({Path(f).name.split("_")[2] for f in glob.glob(str(CDD_DIR / f"DeriBit_{ccy}_*_allStrikes_aggregated.zip"))})
    rows = [{"instrument_name": f"{ccy}-PERPETUAL", "expiry": pd.NaT, "perpetual": True}]
    for m in mats:
        exp = pd.to_datetime(m, format="%d%b%y", utc=True) + pd.Timedelta(hours=EXPIRY_HOUR)
        if exp.weekday() == 4 and exp >= pd.Timestamp(since, tz="UTC"):
            rows.append({"instrument_name": f"{ccy}-{m}", "expiry": exp, "perpetual": False})
    return pd.DataFrame(rows)


def daily_close(instrument: str, start: str, end: pd.Timestamp) -> pd.Series:
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000); t1 = int(end.timestamp() * 1000)
    out = []
    while t0 < t1:
        try:
            r = _get("get_tradingview_chart_data", instrument_name=instrument, start_timestamp=t0,
                     end_timestamp=min(t1, t0 + 5000 * 86_400_000), resolution="1D")
        except requests.HTTPError:                       # instrument never existed
            return pd.Series(dtype=float)
        if r.get("status") == "ok":
            out.append(pd.Series(r["close"], index=pd.to_datetime(r["ticks"], unit="ms", utc=True)))
        t0 += 5000 * 86_400_000
        time.sleep(0.05)
    s = pd.concat(out) if out else pd.Series(dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def futures_closes(ccy: str, start: str = "2023-01-01") -> pd.DataFrame:
    """Long table: date (UTC day of the candle), instrument, expiry, close; the perpetual has expiry NaT."""
    fl = futures_list(ccy, start)
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for _, f in fl.iterrows():
        end = now if f["perpetual"] else min(now, f["expiry"])
        s = daily_close(f["instrument_name"], start, end)
        if s.empty:
            continue
        s.index = s.index.normalize()                     # Deribit 1D candles run 08:00 to 08:00 UTC
        if not f["perpetual"]:
            s = s[s.index + CLOSE_OFFSET <= f["expiry"]]                # only candles that closed before expiry
        rows.append(pd.DataFrame({"date": s.index, "instrument_name": f["instrument_name"],
                                  "expiry": pd.NaT if f["perpetual"] else f["expiry"], "close": s.values}))
    return pd.concat(rows, ignore_index=True)


def forwards(opt: pd.DataFrame, fut: pd.DataFrame) -> pd.Series:
    """Forward for each option row: matching dated future that day, else perp x exp(basis(T) x T)."""
    perp = fut[fut["expiry"].isna()].set_index("date")["close"]
    dated = fut[fut["expiry"].notna()].copy()
    dated["asof"] = dated["date"] + CLOSE_OFFSET
    dated["T"] = (dated["expiry"] - dated["asof"]).dt.total_seconds() / (365 * 86400)
    dated["perp"] = dated["date"].map(perp)
    dated = dated[(dated["T"] >= 2 / 365) & dated["perp"].notna() & (dated["close"] > 0)]
    dated["basis"] = np.log(dated["close"] / dated["perp"]) / dated["T"]
    exact = dated.set_index(["date", "expiry"])["close"]
    F = pd.Series(np.nan, index=opt.index)
    key = pd.MultiIndex.from_arrays([opt["date"], opt["expiry"]])
    F[:] = exact.reindex(key).values
    curves = {d: g.sort_values("T") for d, g in dated.groupby("date")}
    miss = F.isna()
    for d, g in opt[miss].groupby("date"):
        c = curves.get(d); p = perp.get(d)
        if p is None or np.isnan(p):
            continue
        b = np.interp(g["T"], c["T"], c["basis"]) if c is not None and len(c) else 0.0
        F[g.index] = p * np.exp(b * g["T"].values)
    return F


# ---------- Black-76 ----------

def black(F, K, T, sigma, is_call):
    s = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * s ** 2) / s
    d2 = d1 - s
    call = F * norm.cdf(d1) - K * norm.cdf(d2)
    return np.where(is_call, call, call - F + K)


def implied_vol(price_usd, F, K, T, is_call, lo=0.01, hi=5.0, iters=60):
    """Vectorised bisection on Black-76. NaN where the price is outside the no-arbitrage bounds."""
    price_usd, F, K, T = (np.asarray(x, float) for x in (price_usd, F, K, T))
    intrinsic = np.where(is_call, np.maximum(F - K, 0), np.maximum(K - F, 0))
    upper = np.where(is_call, F, K)
    ok = (price_usd > intrinsic) & (price_usd < upper) & (T > 0)
    a = np.full(price_usd.shape, lo); b = np.full(price_usd.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        too_high = black(F, K, T, m, is_call) > price_usd
        b = np.where(too_high, m, b); a = np.where(too_high, a, m)
    iv = 0.5 * (a + b)
    iv[~ok | (iv <= lo * 1.001) | (iv >= hi * 0.999)] = np.nan
    return iv


def black_delta(F, K, T, sigma, is_call):
    d1 = (np.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * np.sqrt(T))
    return np.where(is_call, norm.cdf(d1), norm.cdf(d1) - 1.0)


# ---------- ATM per expiry, constant maturity ----------

def atm_by_expiry(opt: pd.DataFrame, delta_lo: float = 0.2, delta_hi: float = 0.8) -> pd.DataFrame:
    """ATM IV (vol points) per (date, expiry): IV interpolated in k = ln(K/F) at k = 0 from options
    inside the delta band, needing at least one strike on each side of the forward."""
    d = opt.dropna(subset=["iv"])
    d = d[(d["abs_delta"] >= delta_lo) & (d["abs_delta"] <= delta_hi)]
    rows = []
    for (date, exp), g in d.groupby(["date", "expiry"]):
        k = np.log(g["strike"].values / g["F"].values)
        if not ((k < 0).any() and (k > 0).any()):
            continue
        s = pd.Series(g["iv"].values, index=k).groupby(level=0).mean().sort_index()
        rows.append({"date": date, "expiry": exp, "T": float(g["T"].iloc[0]), "F": float(g["F"].iloc[0]),
                     "atm_iv": float(np.interp(0.0, s.index.values, s.values)) * 100, "n": int(len(g))})
    return pd.DataFrame(rows)


def constant_maturity(atm: pd.DataFrame, tenors_days=(30, 90, 180, 365)) -> pd.DataFrame:
    """ATM IV at fixed tenors by linear interpolation of total variance in T between bracketing expiries."""
    out = {}
    for date, g in atm.groupby("date"):
        g = g.sort_values("T")
        T = g["T"].values; w = (g["atm_iv"].values / 100) ** 2 * T
        row = {}
        for h in tenors_days:
            t = h / 365
            if T.min() <= t <= T.max():
                wt = np.interp(t, T, w)
                row[f"atm_{h}d"] = np.sqrt(max(wt, 0) / t) * 100
            else:
                row[f"atm_{h}d"] = np.nan
        row["longest_expiry_days"] = T.max() * 365
        out[date] = row
    return pd.DataFrame.from_dict(out, orient="index").sort_index()


def build(ccy: str, fut: pd.DataFrame, start: str = "2023-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    opt = load_options(ccy, start)
    opt["F"] = forwards(opt, fut)
    opt = opt.dropna(subset=["F"])
    opt["iv"] = implied_vol(opt["close"].values * opt["F"].values, opt["F"].values, opt["strike"].values,
                            opt["T"].values, opt["is_call"].values)
    ok = opt["iv"].notna()
    opt["abs_delta"] = np.nan
    opt.loc[ok, "abs_delta"] = np.abs(black_delta(opt.loc[ok, "F"].values, opt.loc[ok, "strike"].values,
                                                  opt.loc[ok, "T"].values, opt.loc[ok, "iv"].values,
                                                  opt.loc[ok, "is_call"].values))
    atm = atm_by_expiry(opt)
    return opt, atm


def futures_cache(ccy: str, start: str = "2023-01-01", refresh: bool = False) -> pd.DataFrame:
    p = ROOT / "processed" / "deribit" / f"futures_daily_{ccy}.parquet"
    if p.exists() and not refresh:
        return pd.read_parquet(p)
    df = futures_closes(ccy, start)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p)
    return df
