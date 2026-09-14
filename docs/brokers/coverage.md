# Coverage matrix

What each broker has an implementation for. A dash means no module or script exists for it, not
that the broker cannot do it.

| Broker | REST | Quotes | Unified quotes | Order updates | Positions streamed | Instruments | Mapping | Price history | API broker quotes |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Zerodha | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: | :material-check: | :material-check: | :material-check: |
| Dhan | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: | :material-check: | :material-check: | :material-check: |
| Flattrade | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: | :material-check: | :material-check: | :material-check: |
| Shoonya | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: | :material-check: | :material-check: | :material-check: |
| Fyers | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: |
| Groww | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-minus: |
| Kotak | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: |
| IND Money | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: | :material-check: | :material-check: | :material-check: | :material-check: |
| Wisdom Capital | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-check: | :material-minus: |
| Stoxkart | :material-check: | :material-minus: | :material-minus: | :material-minus: | :material-minus: | :material-check: | :material-check: | :material-minus: | :material-minus: |

**REST** is the API class in `stock_brokers/api`. **Quotes** and **Order updates** are `bin/<broker>/quotes`
and `bin/<broker>/order_updates`, and **Unified quotes** the brokers `bin/unified/quotes` reads. **API broker
quotes** are the REST quote modules in service, which the API asks when the quote cache cannot answer.

## How to read the gaps

**Unified quotes.** Every broker with a quote feed is read by `bin/unified/quotes`, but only Zerodha is
verified against a live session so far; the others supply an instrument only when no verified broker streams
it. [Unified scripts](../guides/unified-scripts.md#what-each-brokers-values-mean) lists what each still has to
have confirmed.

**Positions streamed.** Only four brokers send position updates on their order update socket - Fyers, Groww
(derivatives positions only), Kotak and Wisdom Capital - so only they have `persist_positions`. Every
broker's positions still come from its `positions` poller.

**Price history.** Seven brokers serve candles. Groww answers 403 on the historical endpoint,
which is an entitlement rather than a bug; Kotak publishes no candle endpoint at all; Stoxkart has
no candle path. Each reason is recorded in `UNSUPPORTED` in the historical orchestrator rather
than left as a gap to be rediscovered. See [Price history](../guides/price-history.md).

**Mapping.** All ten, with no exceptions - the mapping reads stored rows rather than calling a
broker, so a broker with an instrument master necessarily has a mapping adapter. See
[Instrument mapping](../guides/instrument-mapping.md).

**API broker quotes.** Fyers' and Groww's quote modules exist but are not in service: Fyers' field mapping is
unverified, and Groww's account is not entitled to live data. Wisdom Capital has no quote module. See
[REST API](../guides/rest-api.md#live-quotes).

**Stoxkart.** No quote or order scripts, because its API login is broken on the broker's side. Its
instrument master is a public file needing no login, so that part works, and so does its
mapping.

**Flattrade's order feed is implemented but not running.** The broker permits one websocket per
session, so `flattrade@order_updates` is not enabled and `flattrade@quotes` holds the connection. See
[Known issues](../contributing/known-issues.md#broker-limits).

## Broker lists in the code

They differ, and the differences are deliberate.

| Constant | Count | Where | Contents |
| --- | --- | --- | --- |
| `orchestrator.INSTRUMENT_BROKERS` | 10 | `stock_brokers/instruments/orchestrator.py` | Every broker with an instrument master, Stoxkart included. |
| `segments.MAPPED_BROKERS` | 10 | `stock_brokers/instruments/mapping/utilities/segments.py` | The same ten, but **ordered**: the order they must be mapped in. |
| `orchestrator.CANDLE_BROKERS` | 7 | `stock_brokers/instruments/historical/utilities/orchestrator.py` | Every broker with a candle downloader. |
| `BROKERS` | 9 | each combiner in `bin/unified/`; `ORDER_BROKERS` and `POSITION_BROKERS` (4) in `order_updates` | The brokers that script combines. Stoxkart is absent. |
| `SOURCES` | varies | `utilities/service.py` in the REST API's `broker_quotes` | The broker quote modules in service. |

When adding a broker, all of them need looking at - a broker whose scripts write to Redis but which is
missing from a `bin/unified/` script's `BROKERS` never reaches the unified keys that script writes.

`MAPPED_BROKERS` is the one where position matters rather than just membership. It is not the
same order as `INSTRUMENT_BROKERS`, and appending to it is usually wrong: several adapters resolve
index names against master rows an earlier broker wrote in the same run.
