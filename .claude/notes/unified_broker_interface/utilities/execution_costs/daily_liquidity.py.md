# Notes on `daily_liquidity.py`

Log returns are used because they are the usual input to a volatility figure and treat a rise and a fall of the same size alike. The sample standard deviation (`statistics.stdev`, dividing by n − 1) is used because twenty days is a small sample.

Twenty days matches the latency calibration's window and is about a trading month. Ten days is the floor below which a volatility figure is too noisy to scale an impact estimate.

The estimate check reads the bars from `unified.price_history_adjusted` rather than `unified.price_history`, so a split or bonus in a share does not look like a one-day crash and inflate the volatility; the view leaves options and futures unadjusted. Daily bar volume was checked against the tick feed's day volume on 2026-10-06 for a NIFTY option (515,905 against 516,165 on 4 October, and equal on the two days before), so it is in units like the book.
