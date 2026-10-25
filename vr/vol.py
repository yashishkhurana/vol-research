"""Volatility arithmetic: realised vol from hourly closes, the variance risk premium against a
constant-maturity implied index, and surface summaries (ATM term structure, skew) from a book.

Conventions
- Vols are annualised, in vol points (55.0 = 55%). Hourly log returns, 8,760 hours a year.
- Realised vol over the NEXT h days at time t uses returns in (t, t + h days]. That is what an
  option sold at t with h days to expiry is exposed to, so VRP(t) = IV(t) - RV_next(t) is known
  only at t + h; nothing here lags it for you.
- Delta for moneyness uses Black-Scholes with the instrument's own mark IV and zero rates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

HOURS_PER_YEAR = 24 * 365


def realised_vol(close: pd.Series, window_days: int, forward: bool = False) -> pd.Series:
    """Annualised realised vol from hourly closes. Trailing by default (uses bars <= t);
    forward=True gives the vol of the NEXT window (bars in (t, t + window])."""
    r = np.log(close).diff()
    w = window_days * 24
    if forward:
        return (r.shift(-w).rolling(w, min_periods=int(w * 0.9)).std(ddof=1) * np.sqrt(HOURS_PER_YEAR) * 100)
    return r.rolling(w, min_periods=int(w * 0.9)).std(ddof=1) * np.sqrt(HOURS_PER_YEAR) * 100


def vrp(iv_index: pd.Series, close: pd.Series, horizon_days: int = 30) -> pd.DataFrame:
    """Variance risk premium series: implied (constant-maturity index, vol points) minus realised
    over the following `horizon_days`. Also the variance-space version, which is what a variance
    swap pays: (IV^2 - RV^2) / 100 in vol-point^2 units."""
    idx = iv_index.index.intersection(close.index)
    iv = iv_index.reindex(idx)
    rv_next = realised_vol(close, horizon_days, forward=True).reindex(idx)
    rv_prev = realised_vol(close, horizon_days).reindex(idx)
    out = pd.DataFrame({"iv": iv, "rv_next": rv_next, "rv_prev": rv_prev})
    out["vrp"] = out["iv"] - out["rv_next"]
    out["vrp_var"] = (out["iv"] ** 2 - out["rv_next"] ** 2) / 100
    out["iv_minus_rv_prev"] = out["iv"] - out["rv_prev"]              # what you can see at t
    return out


def bs_delta(spot: float, strike: float, tenor_years: float, iv: float, is_call: bool) -> float:
    if tenor_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return np.nan
    d1 = (np.log(spot / strike) + 0.5 * (iv / 100) ** 2 * tenor_years) / ((iv / 100) * np.sqrt(tenor_years))
    return norm.cdf(d1) if is_call else norm.cdf(d1) - 1.0


def with_delta(book: pd.DataFrame) -> pd.DataFrame:
    b = book.copy()
    b["tenor_years"] = b["tenor_days"] / 365
    b["delta"] = [bs_delta(s, k, t, iv, ty == "call") for s, k, t, iv, ty in
                  zip(b["underlying_price"], b["strike"], b["tenor_years"], b["mark_iv"], b["type"])]
    b["abs_delta"] = b["delta"].abs()
    return b


def _interp_iv_at_delta(g: pd.DataFrame, target_abs_delta: float) -> float:
    g = g.dropna(subset=["abs_delta", "mark_iv"]).sort_values("abs_delta")
    if len(g) < 2 or not (g["abs_delta"].min() <= target_abs_delta <= g["abs_delta"].max()):
        return np.nan
    return float(np.interp(target_abs_delta, g["abs_delta"].values, g["mark_iv"].values))


def surface_summary(book: pd.DataFrame) -> pd.DataFrame:
    """Per expiry: ATM IV (50-delta, interpolated across puts and calls), 25-delta put and call IV,
    skew (25d put - 25d call), total OI, tenor. Uses mark IVs; OTM side only for each wing."""
    b = with_delta(book)
    b = b[(b["tenor_days"] > 0.5) & b["mark_iv"].notna() & (b["mark_iv"] > 0)]
    rows = []
    for exp, g in b.groupby("expiry"):
        calls, puts = g[g["type"] == "call"], g[g["type"] == "put"]
        atm = np.nanmean([_interp_iv_at_delta(calls, 0.5), _interp_iv_at_delta(puts, 0.5)])
        c25, p25 = _interp_iv_at_delta(calls, 0.25), _interp_iv_at_delta(puts, 0.25)
        c10, p10 = _interp_iv_at_delta(calls, 0.10), _interp_iv_at_delta(puts, 0.10)
        rows.append({"expiry": exp, "tenor_days": float(g["tenor_days"].iloc[0]), "atm_iv": atm,
                     "iv_25d_put": p25, "iv_25d_call": c25, "skew_25d": p25 - c25,
                     "iv_10d_put": p10, "iv_10d_call": c10, "n_options": int(len(g)),
                     "oi_contracts": float(g["open_interest"].sum()),
                     "oi_usd": float((g["open_interest"] * g["underlying_price"]).sum())})
    return pd.DataFrame(rows).sort_values("tenor_days").reset_index(drop=True)


def venue_gap(a: pd.DataFrame, b: pd.DataFrame, name_a: str, name_b: str, tol_days: float = 1.0) -> pd.DataFrame:
    """Join two books on (type, strike) and expiry within `tol_days`; report IV gap per matched
    option and the OI on each side. Positive gap = venue b richer than venue a."""
    aa = with_delta(a).dropna(subset=["mark_iv"]); bb = with_delta(b).dropna(subset=["mark_iv"])
    rows = []
    for _, r in bb.iterrows():
        m = aa[(aa["type"] == r["type"]) & (aa["strike"] == r["strike"]) & ((aa["expiry"] - r["expiry"]).abs() <= pd.Timedelta(days=tol_days))]
        if m.empty:
            continue
        m = m.iloc[0]
        rows.append({"expiry": r["expiry"], "tenor_days": r["tenor_days"], "strike": r["strike"], "type": r["type"],
                     "abs_delta": r["abs_delta"], f"iv_{name_a}": m["mark_iv"], f"iv_{name_b}": r["mark_iv"],
                     "gap_vol_pts": r["mark_iv"] - m["mark_iv"],
                     f"oi_{name_a}": m["open_interest"], f"oi_{name_b}": r["open_interest"]})
    return pd.DataFrame(rows)
