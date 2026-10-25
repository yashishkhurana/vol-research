import numpy as np
import pandas as pd

from vr.vol import bs_delta, realised_vol, surface_summary, venue_gap, vrp


def _close(n_days=120, sigma_hourly=0.01, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days * 24, freq="1h", tz="UTC")
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, sigma_hourly, len(idx)))), index=idx)


def test_realised_vol_recovers_sigma_and_forward_uses_future_bars():
    c = _close(200, 0.01)
    rv = realised_vol(c, 30).dropna()
    assert abs(rv.mean() - 0.01 * np.sqrt(8760) * 100) < 5          # ~93.6 vol pts
    fwd = realised_vol(c, 30, forward=True)
    # forward at t equals trailing at t + 30d
    t = c.index[24 * 60]
    assert np.isclose(fwd.loc[t], realised_vol(c, 30).loc[t + pd.Timedelta(days=30)])


def test_vrp_sign_and_variance_form():
    c = _close(200, 0.01)                                           # realised ~94
    iv = pd.Series(110.0, index=c.index)
    d = vrp(iv, c, 30).dropna()
    assert (d["vrp"] > 0).mean() > 0.9                                # implied above realised almost always
    assert np.allclose(d["vrp_var"], (110 ** 2 - d["rv_next"] ** 2) / 100)


def test_bs_delta_bounds():
    assert 0.45 < bs_delta(100, 100, 30 / 365, 60, True) < 0.6
    assert -0.6 < bs_delta(100, 100, 30 / 365, 60, False) < -0.45
    assert bs_delta(100, 200, 7 / 365, 60, True) < 0.05
    assert np.isnan(bs_delta(100, 100, 0, 60, True))


def _book(spot=100.0, tenor=30.0, atm=60.0, skew=5.0, venue_shift=0.0):
    rows = []
    for k in np.arange(60, 150, 5.0):
        for ty in ("call", "put"):
            m = np.log(k / spot)
            iv = atm + venue_shift + (skew * -m * 4 if m < 0 else skew * m * 2)   # puts richer
            rows.append({"instrument_name": f"X-{k}-{ty[0].upper()}", "expiry": pd.Timestamp("2024-02-01", tz="UTC"),
                         "tenor_days": tenor, "strike": k, "type": ty, "mark_iv": iv, "open_interest": 10.0, "underlying_price": spot})
    return pd.DataFrame(rows)


def test_surface_summary_finds_atm_and_put_skew():
    s = surface_summary(_book())
    assert len(s) == 1
    assert abs(s.loc[0, "atm_iv"] - 60.0) < 1.5
    assert s.loc[0, "skew_25d"] > 0                                   # puts richer than calls


def test_venue_gap_measures_shift():
    g = venue_gap(_book(), _book(venue_shift=3.0), "a", "b")
    assert len(g) > 10 and np.allclose(g["gap_vol_pts"], 3.0)
