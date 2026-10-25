# On-chain options maker: design

*A design, not a backtest. What a maker on an on-chain options venue would quote, how it would hedge, and what would break it. Written before any live quoting.*

## What it does
[Quote both sides of BTC/ETH options on an on-chain venue around a reference surface. The reference is Deribit's mark IV, which has the depth; the on-chain venue has the flow. Earn the spread; hedge the delta on a perp; keep vega and gamma inside limits.]

## Quoting
- Reference: Deribit ATM term structure and skew, refreshed every [N] seconds (`vr/vol.py: surface_summary`).
- Spread: [x] vol points either side of reference, wider on wings and short tenors; widen with inventory.
- Size: [per-quote size as a fraction of the venue's OI at that strike].
- Pull quotes when: reference stale, spot moved more than [y]% since last hedge, venue oracle lags Deribit index by more than [z].

## Hedging
- Delta: perp on [venue], rebalanced when net delta exceeds [band]. Cost: fees + funding on the hedge leg (the funding carry work applies here).
- Vega: cap net vega per expiry; offset on Deribit when the cap is hit.
- Gamma: the short-dated book is the risk; cap gamma so a [k]% move inside a hedge interval costs at most [m]% of capital.

## What breaks
- Oracle: the venue's settlement price lags or differs from Deribit's index; a quote can be picked off against a stale oracle.
- Thin books: no partial fills, wide markets, so hedging an on-chain fill on-chain is not possible; the hedge is off-venue.
- Gamma in a squeeze: a 10% hourly move on a short-dated short straddle.
- Venue risk: contract risk, withdrawal delays, the maker's capital is on-chain.
- Toxic flow: the counterparty knows something (the on-chain flow is small and may be informed).

## What would make it a strategy
- Measured: the Derive–Deribit IV gap and the OI behind it (`notes/02_surface.md`).
- Not measured: fill rates, adverse selection on fills, hedge slippage, the venue's fee schedule. These need a live quoting record, not a backtest.

## Capacity
[Derive OI in USD, per currency, from the scan; 1% of that is the size.]
