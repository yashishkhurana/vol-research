# On-chain options maker: design

A design, not a backtest. What a maker on an on-chain options venue would quote, how it would hedge, what would break it, and what can't be known without quoting live. Starting values are stated so they can be argued with; none has been tuned on anything.

## What it does
Quote both sides of BTC and ETH options on an on-chain venue around a reference surface. The reference is Deribit, which has the depth; the on-chain venue has the flow. Earn the spread between them, hedge the delta on a perp, keep vega and gamma inside limits.

The case for it is in `02_surface.md`: where on-chain IV sits against Deribit at matching strikes, and how much open interest is behind it. The case against it is the same table: Derive's open interest is 2.4% of Deribit's on BTC and 23% on ETH, and at marks its whole book is worth about $18m (BTC) and $15m (ETH) of premium.

## Quoting
- Reference: Deribit ATM term structure and 25-delta skew (`vr/vol.py: surface_summary`), refreshed every 30 seconds; a quote is pulled if the reference is older than 90 seconds.
- Spread: 2 vol points either side of reference at the money, 4 on 25-delta wings, 6 beyond; doubled under 3 days to expiry. Shift the whole quote by 0.5 vol points per 10% of the vega limit held, against the inventory.
- Size per quote: 0.5% of the venue's open interest at that strike and expiry, floor one contract.
- Pull all quotes when: spot has moved more than 1.5% since the last hedge; the venue's oracle differs from Deribit's index by more than 0.3%; the perp used for hedging is more than 0.5% from its index.

## Hedging
- Delta: perp on the venue with the deepest book for the underlying, rebalanced when net delta exceeds 2% of capital. Cost is fees plus funding on the hedge leg, which `quant-research` measures.
- Vega: cap net vega per expiry at 0.5% of capital per vol point; above the cap, offset on Deribit rather than widen.
- Gamma: cap so that a 5% move inside one hedge interval costs at most 1% of capital. The short-dated book is where this binds.
- Hedge interval: every hour, or on the delta trigger, whichever first.

## What breaks
- **Oracle.** The venue settles on its own price feed. If it lags Deribit's index, a quote can be picked off against a stale oracle. The 0.3% pull rule is the only defence until the venue's feed is understood.
- **Thin books.** No partial fills and wide markets on-chain, so a fill can't be hedged on-chain; the hedge is off-venue, with transfer and margin delays.
- **Gamma in a squeeze.** A 10% hourly move on a short-dated short straddle costs far more than the premium collected that week.
- **Venue.** Contract risk and withdrawal delays; the maker's margin is on-chain.
- **Toxic flow.** On-chain option flow is small and may be informed. Who fills you decides whether the spread is a premium or a loss.

## What can't be known from a backtest
Fill rate, adverse selection on fills, hedge slippage, and the venue's real fee schedule under volume. Daily closes don't contain any of them. They need a live quoting record on a small book — that is the first deliverable, not a backtest.

## Capacity
1% of the on-chain venue's open interest per currency, from `02_surface.md`. Deribit's OI is the ceiling for offsetting vega.
