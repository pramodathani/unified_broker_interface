"""
Quotes fetched from a broker's REST API, for the instruments the unified quote cache cannot answer for.

One module per broker turns that broker's quote response into a tick in the market feeds' contract
shape, so the tick normalizers in `stock_brokers/instruments/ticks/` - lot conversion, close policy,
rounding, timestamps - apply to it exactly as they do to a streamed tick. `base.py` defines what a
broker module provides; `utilities/` holds the service that decides when to call a broker and the
per-worker API clients.

In service, each validated against the live API: Zerodha, Dhan, Kotak, Flattrade, Shoonya and INDmoney.
Fyers and Groww have modules that are not yet in service, for the reasons `utilities/service.py` gives
beside `SOURCES`.
"""
