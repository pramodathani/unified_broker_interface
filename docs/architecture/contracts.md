# Normalized contracts

Four dictionaries: the tick, the order, the position and the unified quote. Each has a fixed set of
keys, every key is always present, and a field the broker does not supply is `None` rather than
missing. Consumers can therefore rely on the shape without asking which broker a message came from.

The first three are built by each broker's own [scripts](../guides/broker-scripts.md) in `bin/<broker>/`,
each of which carries its own decoding and normalization. Every script's module docstring has the table of
how each field is derived from that broker's own names. The unified quote is built from the ticks by
`bin/unified/instruments/websocket_quotes`.

## The tick

Written by every `bin/<broker>/instruments/websocket_quotes` to the hash `<broker>:quotes:live` and the stream
`<broker>:quotes:stream`, which `bin/<broker>/instruments/store_quotes_to_db` writes to `<broker>.ticks` with the order book
flattened into columns. The REST API's quote modules build the same shape from a broker's quote response
with [`contract_tick`][unified_broker_interface.utilities.broker_quotes.base.contract_tick], so a fetched
quote is normalized exactly as a streamed one.

| Field | Meaning |
| --- | --- |
| `id` | The instrument's name from the broker's instrument file (`NSE:RELIANCE`), or its token when the file does not name it |
| `broker` | The broker the tick came from |
| `instrument_token` | The broker's own token |
| `exchange` | Exchange or segment, in the broker's own spelling |
| `mode` | `ltp`, `quote` or `full` |
| `last_price`, `last_quantity`, `average_price` | Last trade and the day average |
| `volume`, `buy_quantity`, `sell_quantity` | Day volume and total pending quantity each side |
| `ohlc` | `open`, `high`, `low`, `close` |
| `change` | Percentage change against close |
| `oi`, `oi_day_high`, `oi_day_low` | Open interest and its day range |
| `last_trade_time`, `exchange_timestamp` | Epoch seconds, or `None` |
| `depth` | `buy` and `sell` lists of `{quantity, price, orders}` |
| `received_at` | Epoch seconds at which the script decoded the tick |

`received_at` is set locally, not by the broker. The gap between it and `exchange_timestamp` is
the only feed latency measure available for brokers that timestamp their frames at all.

The keys are the same at every broker, but not always the meaning: the token and exchange are in the
broker's own vocabulary, MCX quantities are lots at some brokers, and `close` is today's close at some
brokers once the session has ended. The unified quote below is the form that means the same thing
everywhere.

## The order

Built by `bin/<broker>/orders/api_order_details` from the order book and by `bin/<broker>/orders/websocket_order_details` from the broker's
websocket, onto the same fields on both sides even where the broker names things differently in its order
book and its update stream, and stored as the `order` of each entry in `<broker>:orders:orders`.

| Field | Meaning |
| --- | --- |
| `order_id`, `exchange_order_id`, `parent_order_id` | The broker's, the exchange's and the parent order's ids |
| `status`, `status_message` | The status on the shared vocabulary, and the broker's message |
| `id`, `instrument_token`, `tradingsymbol`, `exchange` | The instrument, as the broker names it |
| `transaction_type`, `product`, `order_type`, `validity` | On the shared vocabulary |
| `quantity`, `filled_quantity`, `pending_quantity`, `cancelled_quantity`, `disclosed_quantity` | Quantities |
| `price`, `trigger_price`, `average_price` | Prices |
| `order_timestamp`, `exchange_timestamp` | ISO timestamps with the IST offset |
| `tag` | The order's tag |

`status` is normalized onto one of six values, so a consumer branches on one vocabulary rather
than ten:

| Status | Meaning |
| --- | --- |
| `PENDING` | Accepted by the broker, not yet at the exchange |
| `OPEN` | Live at the exchange |
| `COMPLETE` | Fully filled |
| `CANCELLED` | Cancelled |
| `REJECTED` | Rejected |
| `EXPIRED` | Lapsed at end of day |

An unrecognised status is passed through uppercased rather than being forced into one of these,
so a broker inventing a new one is visible instead of silently mislabelled.

The broker's untouched payload is never thrown away. In the Redis hash it is the `data` beside `order`, and
`bin/<broker>/orders/store_orders_to_db` stores the whole update in the `raw` column of `<broker>.order_updates`. Order
events are financial records, so a field mapped wrongly has to stay recoverable from the stored row.

The REST API's orders are the same contract, copied field for field by `bin/unified/orders/api_order_details`: with `broker`
and the order's `instrument_id`, and without `raw` and `received_at`. `bin/unified/orders/websocket_order_details`
adds `broker`, `instrument_id` and `observed_at` to each update it combines. See [REST API](../guides/rest-api.md).

## The position

Built by `bin/<broker>/portfolio/positions` from the broker's positions, and by `bin/<broker>/orders/websocket_order_details` at the four
brokers that stream them - Fyers, Groww, Kotak and Wisdom Capital - and stored as the `position` of each
entry in `<broker>:portfolio:positions`. A position is a snapshot rather than an event: each one is the state
of an instrument at a moment, and the history in `<broker>.positions` is the series of snapshots.

| Field | Meaning |
| --- | --- |
| `id`, `instrument_token`, `tradingsymbol`, `exchange`, `segment` | The instrument, as the broker names it |
| `product` | On the shared vocabulary |
| `quantity`, `buy_quantity`, `sell_quantity` | Net quantity, and what was bought and sold |
| `buy_price`, `sell_price`, `buy_value`, `sell_value` | Averages and totals, paid and received |
| `average_price`, `last_price` | The broker's average and last price |
| `realized_pnl`, `unrealized_pnl`, `pnl` | The broker's own profit figures |
| `multiplier`, `lot_size` | The contract's multiplier and lot size, where the broker sends them |
| `day_or_net` | `NET` or `DAY` |
| `updated_at` | When the broker last updated the position, where it says |

`quantity` is net and signed, positive meaning long. `day_or_net` distinguishes the two views where the
broker offers both.

The REST API answers positions in a shape of its own, resolved to an instrument and merged across brokers,
with products such as `delivery`, `intraday` and `carry`. See [REST API](../guides/rest-api.md#positions).

## The unified quote

One quote per unified instrument, whichever broker streams it, written by `bin/unified/instruments/websocket_quotes` to
`unified:quotes:live` and `unified:quotes:stream` and served by the REST API's `/api/instruments/quote`. The
REST API builds a quote fetched from a broker into the same document.

| Group | Fields |
| --- | --- |
| Identity | `instrument_id`, `exchange`, `segment`, `shape`, `symbol`, `underlying_symbol`, `expiry_date`, `strike_price`, `option_type`, `lot_size` |
| Source | `broker`, `broker_token` |
| Prices | `last_price`, `average_price`, `ohlc` (`open`, `high`, `low`), `previous_close`, `change_percent` |
| Quantities, in units | `last_quantity`, `volume`, `buy_quantity`, `sell_quantity`, `oi`, `oi_day_high`, `oi_day_low` |
| Book | `depth.buy`, `depth.sell`: up to five `{price, quantity, orders}`, best first |
| Instants, epoch seconds | `last_trade_time`, `exchange_time`, `received_at` (the broker script decoded it), `unified_at` (the unified script wrote it) |
| Freshness | `stale`, `stale_since` |

What normalized means:

| Field | Rule |
| --- | --- |
| Prices | Rupees, rounded to 2 places, or 4 for currency derivatives. Rounding also removes the float32 noise some feeds carry (2232.6001 is 2232.60). Zero is null, and a negative price is kept only for commodity derivatives. |
| `previous_close` | Always the previous session's close. A broker's `close` is used only where it means that - Zerodha's always, Dhan's only before the session ends (after it, Dhan's `close` is the day's own close) - and otherwise the value seen earlier that day carries forward. |
| `change_percent` | Recomputed from `last_price` and `previous_close`, never taken from the broker; Zerodha's index packets, for one, send points. |
| Quantities | Underlying units, never lots, because exchanges revise lot sizes and a lot count stops being comparable when they do. On MCX that is the contract's quotation unit, so price times quantity is notional: CRUDEOIL volume 67958 lots is 6,795,800 barrels. `lot_size` says what was applied. |
| Open interest | Null for securities. |
| Instants | True UTC. Null when a broker does not send one reliably, or when it lies days away from the tick's receipt - a clock nobody corrected. |
| Book | Levels without both a price and a quantity are dropped, so an empty level means the same at every broker. |

MCX lot sizes come from Groww. The brokers disagree - on 2026-09-13 GOLD OCT had a lot of 100 at Groww
and 1 at the other eight - and Groww's are the ones that match the MCX contract specifications: CRUDEOIL
100, NATURALGAS 1250, GOLD 100, SILVER 30, COPPER 2500, ZINC 5000. On NSE and BSE the brokers agree, and
their common value is used.

Prices are stored as streamed. Splits and bonuses are applied on read through `unified.ticks_adjusted`,
from the same factors as the [unified price history](../guides/unified-price-history.md). How a tick becomes
a quote - resolution, session windows and which broker owns an instrument - is in
[Unified scripts](../guides/unified-scripts.md#live-quotes-websocket_quotes).

## The shared vocabulary

Brokers describe the same order in wildly different words, so each broker's spelling is mapped onto one set
of terms, listed below. Keys are compared case-insensitively. There is no shared module holding the tables:
each `bin/<broker>/` script that normalizes orders carries its own copy of the ones it needs, and those
copies must agree with this page.

=== "Transaction types"

    `BUY`, `SELL`

    Brokers spell these as `B`/`S`, `1`/`-1`, `1`/`2`, or `BUY_ORDER`/`SELL_ORDER`.

=== "Products"

    `CNC`, `MIS`, `NRML`, `CO`, `BO`, `MTF`, `ARB`

    The Noren brokers abbreviate to a single letter - `C` cash, `M` margin, `I` intraday,
    `H` cover, `B` bracket. `B` is a product here and a side in the transaction table; they are
    different tables, so the letters do not collide.
    Stoxkart's scripts also read `CARRY FORWARD` as `NRML`, `COVER ORDER` as `CO` and `BRACKET ORDER` as `BO`.

=== "Order types"

    `MARKET`, `LIMIT`, `SL`, `SL-M`

    Spelled variously `MKT`, `LMT`, `L`, `SL-LMT`, `STOPMARKET`, or as the numbers 1 to 4.
    Stoxkart's scripts also read `RL` as `LIMIT`, `RL MKT` and `RL-MKT` as `MARKET`, `STOPLOSS LIMIT` as `SL`, and `STOPLOSS MARKET` and `SL MKT` as `SL-M`.

=== "Validities"

    `DAY`, `IOC`, `GTT`, `GTC`, `GTD`

    `EOS` and `0` normalize to `DAY`; `IMMEDIATE` and `1` to `IOC`.
    Stoxkart's scripts also read `EOTODY` and `EOSESS` as `DAY`.

=== "Statuses"

    `PENDING`, `OPEN`, `COMPLETE`, `CANCELLED`, `REJECTED`, `EXPIRED`

    Underscores are read as spaces and repeated spaces collapsed before a spelling is looked up, so Kotak's
    lower-case `modify after market order req received` and Groww's `TRIGGER_PENDING` match. A spelling not
    listed is passed through upper-cased. Stoxkart's two order scripts carry a smaller table of the spellings
    Stoxkart uses, and every spelling in it maps as below.

    | Status | Spellings |
    | --- | --- |
    | `PENDING` | `PENDING`, `TRANSIT`, `VALIDATION PENDING`, `PUT ORDER REQ RECEIVED`, `TRIGGER PENDING`, `AMO REQ RECEIVED`, `PENDINGNEW`, `O-PENDING`, `MODIFY AMO REQ RECEIVED`, `AFTER MARKET ORDER REQ RECEIVED`, `AMO PENDING`, `MODIFY AFTER MARKET ORDER REQ RECEIVED`, `QUEUED`, `PROCESSING`, `SL-PENDING` |
    | `OPEN` | `OPEN`, `OPEN PENDING`, `NEW`, `REPLACED`, `ACKED`, `APPROVED`, `MODIFICATION REQUESTED`, `MODIFIED`, `MODIFY VALIDATION PENDING`, `MODIFY PENDING`, `PARTIALLY FILLED`, `PARTIALLY EXECUTED`, `PLACED`, `PART TRADED`, `PARTIALLYFILLED`, `PENDINGREPLACE`, `CONFIRMED`, `PARTIALLY TRADED`, `INITIATED` |
    | `COMPLETE` | `COMPLETE`, `COMPLETED`, `TRADED`, `FILLED`, `EXECUTED`, `FULLY EXECUTED`, `DELIVERY AWAITED`, `SUCCESS` |
    | `CANCELLED` | `CANCELLED`, `CANCELED`, `CANCEL`, `CANCEL PENDING`, `CANCELLATION REQUESTED`, `PENDINGCANCEL`, `CANCELLED AFTER MARKET ORDER`, `AMO CANCELLED`, `PARTIALLY FILLED - CANCELLED` |
    | `REJECTED` | `REJECTED`, `REJECT`, `FAILED`, `ABORTED` |
    | `EXPIRED` | `EXPIRED`, `PARTIALLY FILLED - EXPIRED` |

    The after-market and modification spellings were added on 2026-09-15, after a live modify test stored
    Zerodha's `MODIFY AMO REQ RECEIVED`, Kotak's `AFTER MARKET ORDER REQ RECEIVED` and
    `MODIFY AFTER MARKET ORDER REQ RECEIVED`, and INDmoney's `SUCCESS` unmapped. INDstocks documents `SUCCESS` as
    "Order has been successfully executed", and its other spellings here, `QUEUED`, `PROCESSING`, `SL-PENDING`,
    `INITIATED`, `ABORTED` and the two `PARTIALLY FILLED - …` endings, come from its
    [order status types](https://api-docs.indstocks.com/normal_orders/).

## The parent order

Built by `bin/unified/orders/order_engine` and held in the `unified:orders:parents` hash, one entry per
`parent_order_id`. A parent order is one thing a caller asked for; a leg is one order the engine actually sent to a
broker on its behalf. A plain order is the degenerate case, one parent with one leg.

| Field | Meaning |
| --- | --- |
| `parent_order_id`, `parent_tag` | The parent's id, and the sixteen-character tag a leg the engine invents carries to the broker |
| `intent_id` | The intent `POST /api/orders/place` wrote for it |
| `synthetic_type` | The kind of order, `simple` for a plain one |
| `state` | `received`, `working`, `protecting`, or one of the four endings below |
| `instrument_id`, `tag` | The instrument every leg is for, and the caller's own tag |
| `body`, `parameters` | The caller's request verbatim, and what the order type needs beside it |
| `legs` | One entry per broker order, with `leg_id`, `role`, `state`, `broker`, `broker_order_id`, `tag_sent`, `identifier_sent`, the quantities and prices, and `outcome` |
| `sequence` | The last transition number recorded, which is what recovery folds duplicates on |
| `created_at`, `updated_at`, `last_error` | When, and why it last failed |

A parent ends in one of four states, and the difference between them matters to whoever reads it:

| State | Meaning |
| --- | --- |
| `completed` | Everything the order was for has happened |
| `cancelled` | It was stopped deliberately |
| `rejected` | A broker refused it, or it was refused before anything was sent; nothing is live |
| `failed` | The engine does not know what the broker has. A person must look. |

A leg runs `planned`, `sending`, `sent`, `acknowledged`, `partially_filled`, then `filled`, `rejected`, `cancelled`
or `unknown`. `sending` is written and committed *before* the request leaves, so a leg found in it after a restart
means an order may exist at the broker that the engine never heard the answer to. `unknown` is deliberately neither
live nor finished.

The hash is a cache. `unified.synthetic_order_events` is the record: every transition is written and committed before
it is acted on, and the engine rebuilds every unfinished parent from it on start by replaying the rows through the
same state machine the live path uses.

## Where the contracts are enforced

Nowhere, structurally - there is no schema validation at runtime. Each script builds its dictionaries with
every key written out, and its docstring states where each field comes from.
None of the offline checks tests these dictionaries; they are `python -m test_runs.candle_parse` for the candle parsers, `python -m test_runs.unified_ticks_sessions` for the session calendar, `python -m test_runs.order_routes` for the REST API's order routes, `python -m test_runs.contract_sizes` for the contract size rules, `python -m test_runs.order_engine_routes` and `python -m test_runs.order_engine` for the order engine, and `python -m test_runs.connection_warming` for broker connection warming.
See [Test runs](../guides/test-runs.md).
