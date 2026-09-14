# Notes on `unified_broker_interface/utilities/broker_orders/utilities/write_service.py`

## Which tick a placement's price is checked against

`OrderWriteService._check_handle` refuses a price or trigger price that is not a whole number of ticks. The tick is `InstrumentCatalogue.agreed_tick_size` over every broker's handle, which is the same `tick_size` that `/api/instruments/details` answers.

Until 2026-09-14 the tick was the first one found at Zerodha, Fyers, Groww, Shoonya or Wisdom Capital, held in a `RUPEE_TICK_BROKERS` tuple. That list existed because Dhan, Kotak, INDmoney and Stoxkart mapped ticks in paise in some segments. Once the mapping converted every tradeable segment to rupees (commit `67c432f`), the list only did harm: an instrument that none of those five brokers carried had its price never checked at all.

Two cases are still not checked, and are left to the broker's own validation:

- **The brokers tie, or none sends a tick.** `agreed_tick_size` answers `None`, and guessing between two disagreeing figures could refuse a valid price.
- **An uncategorised instrument.** The uncategorised catch-alls still mix paise, rupees and ten-million scaling within one broker, and such an instrument is usually carried by a single broker, so its one tick could be a hundred times too large.

The lot size check still uses the chosen broker's own `lot_size`, because on MCX the brokers mean different things by a lot and the quantity is sent to that broker.
