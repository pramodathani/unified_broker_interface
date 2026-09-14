# Notes on `stock_brokers/instruments/mapping/base.py`

## Tick sizes of zero or below are stored as null

`BrokerMappingAdapter.to_broker_fields` stores a tick size of zero or below as `None`. On 2026-09-14 these were the only such values in `unified.broker_mappings` for that date:

| Broker | Value | Where |
| --- | --- | --- |
| Zerodha | `0` | every NSE, BSE and MCX index, and some uncategorised rows |
| Shoonya | `0` | NSE indices and some uncategorised rows |
| Kotak | `-1` | NSE indices and some BSE uncategorised rows |
| Dhan | `0` | one NSE index |

None of them is a unit to convert. A broker sends them where it has no tick for the row, and an instrument cannot move in steps of zero or of a negative amount. `InstrumentCatalogue.agreed_tick_size` already ignored them, and the order price check already skipped a tick that was not positive, so the only visible effect is that `carried_by` in `/api/instruments/details` now shows `null` rather than a misleading `0.0` or `-1.0`.

The rule lives in the base class rather than in each rules file because it holds for every broker and every segment, including the uncategorised catch-alls, whose other values are still left as sent. The raw value stays in `<broker>.instruments`.

## Why index ticks were brought into rupees

The trigger was the `tradingmachine` project, whose `Instrument` reads `tick_size` from `/details`. For NSE's NIFTY index the brokers' figures were `0.05` (Dhan, Fyers), `1.0` (Stoxkart), `-1` (Kotak) and `0` (Zerodha, Shoonya). For MCX indices the majority vote picked `1.0`, which is a hundred times too big, and for BSE indices such as SENSEX it tied and answered `null`.

The units were settled from stored prices in `unified.price_history` over the 120 days before 2026-09-14:

| Segment | Prices checked | Not a multiple of 0.05 | Not a multiple of 0.01 |
| --- | --- | --- | --- |
| `nse_equity_indices`, daily | 40,820 | 326, all INDIA VIX and Nifty50 USD | 0 |
| `bse_equity_indices`, daily | 21,580 | 17,348 | 0 |

So NSE indices move in steps of 0.05, as Dhan and Fyers say, and BSE indices in steps of 0.01, as Fyers and mostly Dhan say. Fyers gives INDIA VIX 0.01, which the prices confirm, while Dhan gives it 0.05.

For MCX indices, Kotak's figures (1, 5, 100) and Stoxkart's (1, 100) are a hundred times Wisdom Capital's (0.01, 0.05, 1.0) instrument by instrument, which is the same paise convention both brokers use in their tradeable segments. Kotak's and Stoxkart's rules files therefore divide those by 100, and Stoxkart's NCDEX indices, which show the same pattern, too.

Stoxkart's `1.0` on every NSE and BSE index row and Wisdom Capital's `1.0` on every BSE index row are placeholders rather than paise: the same constant appears on NSE, where dividing by 100 would give 0.01 against the real 0.05. Those are dropped in each broker's own `to_broker_fields`, through `NULL_TICK_SEGMENTS`.

The earlier dates in `unified.broker_mappings` were corrected on 2026-09-14 with one `UPDATE` applying the same three rules, because `bin/unified/map_instruments` refuses to re-map a date older than the newest one mapped.
