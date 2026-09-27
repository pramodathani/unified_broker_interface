# Notes on `unified_broker_interface/utilities/broker_orders/stoxkart.py`

## Why the Algo-ID is read from the settings

On 2026-09-15 Stoxkart accepted after-market orders carrying `X-Algo-Id: 99999`, the code of the non-registered strategy `NSE-BSE_NON_REGISTERED` (see the note on `blueprints/orders.py`). In the live test of 2026-09-27 it refused all 14 orders that reached it with `invalid algo_id`, although the requests carried the same header and body value. Something changed on Stoxkart's side, and the value it now expects cannot be worked out from this code or its documentation, which mentions neither the field nor the header. Guessing values with real orders was not done.

`algo_identifier` therefore reads `algo_id` from Stoxkart's settings document and falls back to `ALGO_IDENTIFIER`, so the right id can be stored in MongoDB and picked up without a release once Stoxkart confirms it. Both the header and the body use it, and so does every cancel and modify, since they share `headers`.
