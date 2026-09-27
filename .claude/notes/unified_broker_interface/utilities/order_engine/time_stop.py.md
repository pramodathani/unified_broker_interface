# Notes on `unified_broker_interface/utilities/order_engine/time_stop.py`

## Why minutes are refused on a closed day

`minutes` are counted from the moment the order arrives. On a weekend or holiday that would close the position, or cancel the after-market entry, minutes later on a day nothing trades. There is no single right reading of "20 minutes" before the market opens, so the order is refused with a pointer to `until_time`, which does have one.
