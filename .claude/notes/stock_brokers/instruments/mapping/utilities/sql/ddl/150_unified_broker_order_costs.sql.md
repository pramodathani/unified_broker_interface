# Notes on `stock_brokers/instruments/mapping/utilities/sql/ddl/150_unified_broker_order_costs.sql`

`unified.broker_order_costs` holds one row per broker: the order messages it allows per second, minute, hour and day, and the brokerage it charges for one delivery, F&O and intraday order. The column names are the ones the user gave in the table they supplied on 2026-09-29, and the seed rows are that table's values, with the brokers renamed to the names the code uses (`kotak` for Kotak Neo, `shoonya` for Shoonya (Finvasia)).

It is an ordinary table, not a hypertable, because it has ten rows that change a few times a year.

A limit may be `NULL`, which means the broker sets no limit for that window. The `CHECK` constraints refuse zero and negative limits and negative fees, so a mistyped value is rejected when it is written rather than discovered when orders are routed by it.

The seed uses `ON CONFLICT (broker) DO NOTHING`. This file runs before every daily mapping run, and the rows are meant to be edited by hand afterwards; a seed that updated on conflict would overwrite those edits every morning.

The file lives with the mapping DDL because that is the runner for the `unified` schema's ordinary tables and it runs daily, so the table exists on any database the mapping has run against.

## Margin columns (added 2026-09-30)

`margin_multiplier_intraday`, `margin_multiplier_fno` and `margin_multiplier_commodity` are how much more than the exchange's own margin each broker charges, as a ratio: 1.000 means the exchange's margin exactly. The lowest-cost selector multiplies its own estimate of the exchange margin by these before comparing it with the broker's free cash. `gives_hedge_benefit` says whether the broker's margin for several legs priced together is lower than their sum, so the selector may price a basket as a hedged whole. `margin_calibrated_at` is written by `bin/unified/orders/margin_calibration` whenever it measures a broker.

The seed values were measured on 2026-09-30 at about 10:40 IST, by sending the same reference orders (1 INFY share CNC and MIS, 1 lot of NIFTY futures, 1 lot of a NIFTY call sold and bought, 1 lot of crude oil futures, and a NIFTY iron condor) to every broker's margin calculator and dividing each answer by the exchange margin the other brokers agreed on (INFY MIS 203.48, NIFTY futures 167,109, crude oil 271,073). Flattrade, Shoonya and Wisdom Capital charge noticeably more than the exchange; Wisdom Capital's intraday margin is 37% more. Fyers' basket calculator gave no hedge benefit in either leg order, although its documentation says a BUY listed before a SELL gets one, so it is seeded `FALSE`. Kotak and INDmoney have no basket calculator, so their hedge column is `NULL`, which the selector reads as no benefit. Stoxkart has no margin calculator at all, so all of its margin columns are `NULL`, and the selector uses the configured default multiplier for it. INDmoney does not cover MCX in its calculator, and Wisdom Capital answered zero for crude oil, so those commodity cells are `NULL` too.

A `NULL` multiplier means "not measured", not "no surcharge". The seed is an `UPDATE` that only fills cells that are still `NULL` and only for rows the calibration job has never written, for the same reason the insert does nothing on conflict: this file runs every morning, and must not overwrite a hand edit or a calibration.

## Latency columns

`latency_cost_bps_intraday`, `latency_cost_bps_delivery`, `latency_cost_bps_fno`, `broker_answer_milliseconds` and `latency_calibrated_at` were added on 2026-10-06 for `bin/unified/orders/latency_calibration`. They have no seed: unlike the margin multipliers, which a person measured by hand, these come only from the order engine's own fills, so an empty cell honestly means "not enough legs yet". The latency costs have no `CHECK` constraint because they can be negative: a broker whose answers coincide with the price moving in the order's favour has a negative cost. Nothing reads them yet; `BrokerCostTable` names its columns explicitly, so adding them changed nothing for the selector.
