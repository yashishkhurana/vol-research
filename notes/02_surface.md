# Today's surface: Deribit term structure and skew, and Derive against Deribit

*Second note. One snapshot, 25 Oct 2026, 09:41 UTC. Not a backtest.*

**Result:** [YASHISH]

## Data
- Deribit: every live BTC and ETH option, `public/get_book_summary_by_currency` (`vr/deribit.py`). BTC 920 options, ETH 782, 12 expiries each.
- Derive (on-chain): every active option, v3 `public/get_all_instruments` and `public/get_tickers` per expiry (`vr/derive.py`). BTC 626, ETH 754, 12 expiries each.
- Summary per expiry (`vr/vol.py: surface_summary`): ATM vol at 50 delta, 25- and 10-delta wings, skew = 25d put − 25d call. Cross-venue match on expiry, strike and type (`venue_gap`).

## Deribit term structure and skew

| | BTC | ETH |
| --- | --- | --- |
| 1-day forward | $80,165 | $2,324 |
| ATM vol, 1–5 days | 33–35% | 47–51% |
| ATM vol, 5–11 months | 38–39% | 52–54% |
| 25-delta skew, 1–5 days | 3–5 points | 7–9 points |
| 25-delta skew, 11 months | 1.8 | −0.2 |

Both curves slope up. Puts are richer than calls at the front, flattening out the curve; ETH's front skew is twice BTC's and turns slightly to calls at 11 months. Open interest sits in two expiries: 30 Oct and 25 Dec, about $11bn each on BTC.

## Derive against Deribit

| | BTC | ETH |
| --- | --- | --- |
| Matched options | 496 | 570 |
| Median mark-vol gap, Derive − Deribit | −0.12 | −0.07 |
| Matched options with a Derive bid and ask | 255 | 270 |
| Median Derive half-spread | 1.1 vol pts | 1.1 vol pts |
| Derive bid above Deribit mark | 5 | 4 |
| Derive ask below Deribit mark | 5 | 3 |
| Derive open interest, notional | $756m | $818m |

Derive's marks sit within about 0.1 vol point of Deribit's, and its quotes straddle Deribit's mark on all but about ten options per coin. Its open interest is mostly out-of-the-money calls: on ETH, March 2027 calls at 5,000 and 7,000 (forward 2,366) hold about $390m of notional; on BTC the largest are 90–100k calls.

Notional is not premium. At Derive's marks the whole book is worth $18.3m on BTC and $15.2m on ETH. The two ETH March 2027 calls are marked at $14.7 (5,000 strike, delta 0.045) and $5.2 (7,000, delta 0.016): about $1.6m of premium behind the $390m.

[YASHISH: what it means]

## Limits
- One snapshot; the two venues were read within 15 seconds of each other.
- Mark vols, not fills. Open interest shows where positions sit, not who opened them.

## Reproduce
```bash
python -m vr.deribit book && python -m vr.derive book && python scripts/vol_scan.py   # -> reports/scan/
```
