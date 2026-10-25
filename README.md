# vol-research

Options volatility research on BTC and ETH. Implied against realised, and Deribit against on-chain venues. Same method as [quant-research](https://github.com/yashishkhurana/quant-research): every number from a script, parameters written down before results, negative results stated.

## Notes
- `notes/01_vrp.md` — the variance risk premium: Deribit's DVOL against the realised vol of the next 30 days, 2021–2026, and ATM implied vol at 30–270 days rebuilt from daily option prices, 2023–2026.
- `notes/02_surface.md` — today's surface on Deribit and Derive: term structure, skew, and the IV gap between venues with open interest on each side.
- `notes/03_maker.md` — design for an on-chain options maker: what it quotes, how it hedges, what breaks.

## Data
- `vr/deribit.py` — DVOL (hourly since 2021) and the live option book, public API.
- `vr/derive.py` — Derive (on-chain) instruments and tickers, public API.
- `vr/spot.py` — Binance hourly spot closes for realised vol.
- `vr/term.py` — implied vol from daily Deribit option prices (CryptoDataDownload's per-expiry files), forwards from Deribit's dated futures, constant-maturity ATM. Tested.
- `vr/vol.py` — realised vol, VRP, Black–Scholes delta, surface summary, cross-venue gap. Tested.

## Reproduce
```bash
pip install -e ".[dev]" && pytest
python -m vr.spot --start 2021-01-01
python -m vr.deribit dvol
python -m vr.deribit book && python -m vr.derive book
python scripts/run_vrp.py && python scripts/vol_scan.py
# Deribit options by expiry from CryptoDataDownload into data/raw/cdd/deribit_options/, then:
python scripts/run_term_vrp.py
```
