import numpy as np
import pandas as pd

from vr.term import atm_by_expiry, black, black_delta, constant_maturity, implied_vol


def test_implied_vol_round_trip_calls_and_puts():
    F, T = 60_000.0, 0.5
    K = np.array([40_000, 55_000, 60_000, 70_000, 90_000], float)
    sig = np.array([0.8, 0.6, 0.55, 0.6, 0.75])
    for is_call in (True, False):
        p = black(F, K, T, sig, is_call)
        iv = implied_vol(p, np.full(5, F), K, np.full(5, T), np.full(5, is_call))
        assert np.allclose(iv, sig, atol=1e-6)


def test_implied_vol_nan_outside_bounds():
    iv = implied_vol(np.array([5.0, 70_000.0]), np.array([60_000.0, 60_000.0]), np.array([50_000.0, 50_000.0]),
                     np.array([0.5, 0.5]), np.array([True, True]))
    assert np.isnan(iv).all()                       # below intrinsic, above the forward


def test_atm_interpolates_at_the_forward_and_needs_both_sides():
    rows = [{"date": 1, "expiry": 1, "T": 0.25, "F": 100.0, "strike": k, "iv": v, "abs_delta": 0.5}
            for k, v in ((90.0, 0.60), (110.0, 0.50))]
    a = atm_by_expiry(pd.DataFrame(rows))
    k1, k2 = np.log(0.9), np.log(1.1)
    assert np.isclose(a["atm_iv"].iloc[0], 100 * (0.60 + (0.50 - 0.60) * (0 - k1) / (k2 - k1)))
    one_side = pd.DataFrame([r | {"strike": 120.0} for r in rows])
    assert atm_by_expiry(one_side).empty


def test_constant_maturity_interpolates_total_variance_and_does_not_extrapolate():
    atm = pd.DataFrame({"date": [1, 1], "T": [60 / 365, 120 / 365], "atm_iv": [50.0, 60.0]})
    cm = constant_maturity(atm, (90, 180))
    w = np.interp(90 / 365, atm["T"], (atm["atm_iv"] / 100) ** 2 * atm["T"])
    assert np.isclose(cm.loc[1, "atm_90d"], np.sqrt(w / (90 / 365)) * 100)
    assert np.isnan(cm.loc[1, "atm_180d"])


def test_black_delta_signs():
    assert 0.5 < black_delta(100.0, 100.0, 0.25, 0.6, True) < 0.6
    assert -0.5 < black_delta(100.0, 100.0, 0.25, 0.6, False) < -0.4
