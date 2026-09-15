# Notes on `stock_brokers/instruments/ticks/utilities/registry.py`

## What `NORMALIZERS` holds

`NORMALIZERS` has one entry for every broker with a market feed. Until 2026-09-15 a comment above it said that Stoxkart had no feed and so no normalizer. That stopped being true when `bin/stoxkart/quotes` was written, so the comment was removed and Stoxkart's normalizer was added.

Stoxkart's feed is the broadcast websocket its trading website uses, `wss://broadcasting-v2.stoxkart.com/`, because the quote websocket in its API documentation could not be reached. The ticks `bin/stoxkart/quotes` writes have the same shape as every other broker's, so the normalizer is an ordinary `TickNormalizer`. The measurements behind its attributes are in the module docstring of `stock_brokers/instruments/ticks/stoxkart.py`.

Being registered here does not put Stoxkart into the REST API's quote fallback. That needs a `broker_quotes/stoxkart.py` source in `SOURCES`, which has not been written.
