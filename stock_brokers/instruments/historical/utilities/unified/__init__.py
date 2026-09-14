"""
One price history per unified instrument, built from the brokers' own price tables.

`unified.price_history` holds every instrument's bars under its `instrument_id`. Equities,
exchange traded funds and investment trusts are stored unadjusted and adjusted on read from
`unified.adjustment_factors`; everything else is stored as the broker served it.

- `sources` decides which broker supplies which instrument and interval.
- `resolution` finds the instrument behind each broker series.
- `calendar` knows which days each exchange traded.
- `loader` copies bars across.
- `yahoo` and `factors` build the adjustment factors from Yahoo Finance.
- `verify` checks the result.
"""
