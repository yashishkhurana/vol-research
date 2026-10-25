# The 30-day variance risk premium, BTC and ETH, 2021–2026

Deribit's DVOL index (30-day constant-maturity implied vol) against the realised vol of the next 30 days, from Binance hourly closes. Mar 2021 to late Sep 2026; the last 30 days have no "next 30 days" yet.

**Result:** selling 30-day vol has been paid less every year. BTC: 16 vol points in 2021, 1 in 2026. ETH went negative in 2025. The losses sit in a few squeeze months.

## Why it should exist
Option buyers pay for insurance. Sellers are paid implied vol and pay out realised. If buyers overpay on average, implied sits above realised and the seller collects the gap.

## Data
- DVOL hourly, `vr/deribit.py`, from 2021-03-24.
- BTCUSDT and ETHUSDT hourly closes, Binance spot, `vr/spot.py`.
- Realised vol: hourly log returns over the next 30 days, annualised. One observation a day at 00:00 UTC.

## Result

| | Mean VRP | Median | Days implied > realised | Worst 10% of days |
| --- | --- | --- | --- | --- |
| BTC | +7.9 | +8.4 | 74% | −9.3 |
| ETH | +5.3 | +6.2 | 66% | −19.6 |

Vol points: implied minus what the coin then did.

| BTC | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- | --- |
| Mean VRP | +16.4 | +13.0 | +7.3 | +6.3 | +3.7 | +1.1 |
| Days positive | 87% | 73% | 76% | 77% | 71% | 59% |

| ETH | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
| --- | --- | --- | --- | --- | --- | --- |
| Mean VRP | +10.9 | +10.7 | +6.0 | +2.5 | −1.3 | +3.9 |
| Days positive | 78% | 64% | 75% | 66% | 51% | 66% |

Worst months to have sold, by month of sale: BTC Jan 2026 (−16.1), Feb 2025 (−13.8), Apr 2021 (−13.6), Jul 2024 (−10.7). ETH Apr 2021 (−48.8), Feb 2025 (−24.3), May 2021 (−22.1). A losing stretch lasts 4 days on BTC and 6 on ETH at the median; the longest ran 41 and 59 days.

Nov 2022 was one of the best months to sell: implied jumped on FTX and realised then calmed, +33.7 on BTC.

![vrp](../reports/vrp/vrp.png)

## What it means
[Yashish's sentence.]

## Limits
- 30-day only. Longer tenors are not in DVOL; today's term structure is in `02_surface.md`, as a snapshot.
- 2,015 daily observations of overlapping 30-day windows are about 67 independent ones.
- DVOL is an index. No fees, no hedging cost, no path: this is the premium, not a strategy's return.
- Realised vol from hourly closes reads slightly differently from daily closes.

## Reproduce
```bash
python -m vr.spot --start 2021-01-01 && python -m vr.deribit dvol && python scripts/run_vrp.py
```
