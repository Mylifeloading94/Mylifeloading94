# XAUUSD (Gold) Liquidity Scalping Strategy

Source: Brad Gold's video "Last month I made 566K trading gold" (profit claim is his own, unverified).
Style: scalping, 1H + 15M structure, liquidity sweeps. Spec as supplied by the user; implemented in `liq_scalp.py`.

## 5-step framework
1. **Trend (1H + 15M aligned).** Both bullish -> longs only; both bearish -> shorts only; misaligned -> skip.
   Bullish = higher highs and higher lows. Mark the 1H swing low / high as the trading range.
2. **Liquidity and POIs.** Uptrend: demand zones; downtrend: supply zones. POIs = supply/demand, order blocks, FVGs.
   Liquidity rests below swing/internal lows (longs) or above highs (shorts).
3. **Wait for price to reach a 15M POI.** Never enter in the middle of nowhere.
4. **Entry model - a liquidity sweep is required.**
   Aggressive: enter right after the sweep at the POI. Conservative: wait for a 15M market shift, enter on the pullback
   into the zone that caused it. Brad's variant: after the sweep, wait for one extra confirming candle with real momentum.
5. **Stop / target.** Stop just beyond the extreme that swept the liquidity. Target: nearest 15M swing high (longs) /
   swing low (shorts); alternative: next POI; 1H swing is the larger, less conservative target.

## Suggested risk rules (not from the video)
Fixed 0.5-1% risk, lot size from stop distance, max daily loss, max trades per day, no revenge trading,
no adding to losers, no moving stops, avoid high-impact news.

## Caveats stated in the spec
Gold is volatile; the video's profit figures are unverified and it promotes the creator's paid products;
zone and liquidity marking is subjective.
