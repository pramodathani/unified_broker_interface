# Notes on `impact_coefficients.py`

The coefficient is kept per asset class (`securities`, `currency`, `commodity`, the classes `TradeableSegments.ASSET_CLASSES` already defines) rather than per segment or per instrument, because there is no data to tell segments apart yet; a finer key can be added when fitting shows a difference.

`is_fitted` exists so that anything acting on an estimate later can tell a textbook number from a measured one, and so the estimate check can say which it is using.
