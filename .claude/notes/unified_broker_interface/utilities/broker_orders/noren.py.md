# Notes on `unified_broker_interface/utilities/broker_orders/noren.py`

## Finding a placed order after a reset (2026-10-21)

`find_placed_order` backs `BrokerOrders.recover_after_reset` (see the note on `base.py` for the incident and the evidence). It reads `POST {BASE_URL}/OrderBook` with `jData={"uid": ...}` and the place request's own `jKey`, parsed from the end of the encoded body, so it needs no access to Redis or the login store. It sends on a one-off session so a stale pooled connection cannot reset the read as well.

- A dict answer containing `no data` is Noren's empty book, the same marker `bin/flattrade/orders/api_order_details` uses, and counts as `absent`. Any other dict is a refusal (such as an expired session) and gives `cannot_tell`.
- `matches_request` requires `exch`, `tsym`, `trantype`, `prd`, `prctyp`, the quantity, the price for `LMT` and `SL-LMT`, the trigger price when sent, and `remarks` when the request carried a tag. Numbers are compared as floats because Noren returns `prc` as `"434.30"` while the request sends `"434.3"`.
- The time window is one-sided: the order's `norentm` must be no earlier than `LOOKUP_EARLY_SECONDS` (5) before the request was sent, allowing for Noren's clock running behind ours. There is no upper bound, because the book is read straight after the reset. `norentm` comes in either Noren form (`HH:MM:SS DD-MM-YYYY` or `DD-MM-YYYY HH:MM:SS`) and is India time.
- Exactly one match is `found`; two or more is `cannot_tell`, never a guess, in the spirit of `OrphanMatcher`. An identical order placed by the same caller within five seconds before (such as a script retrying by hand) would make two matches and leave the outcome unknown, which is the safe direction.

`examples/.../NorenOrders/example_3_finding_an_order_after_a_reset.py` shows the matching with fixed times.
