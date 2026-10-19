# stop_slippage_measurement.py

Added on 2026-10-19 as the second stage of a real breakeven stop, after the charges and `BreakevenPrice`.

## Why it does not use unified.order_execution_costs

That table measures a leg against the mid-price when the leg was decided, and has no trigger price, so it cannot say how far a stop filled beyond its trigger. The event log has everything: the trigger level in `parent_received`'s `parameters.plan.order.trigger.price_crosses`, the firing in `parameters_changed` (`parts.<name>.fired_at`, an epoch float, or `memory.trigger.fired` before that is written), and the fill in `leg_update`.

## Following a stop that did not fill

On 2026-10-19, 63 of the 173 sell stops that fired got no fill of their own. The kaprekar call-put switch script cancels a held stop whose order has not filled within a few seconds, or whose limit UBI is holding back, and closes the position with a marketable `simple` sell. That sell is the stop's real exit and the worst one, up to 3.60 below the trigger that day, so the measurement takes the first other order on the same instrument and side requested within `CLOSE_WINDOW_SECONDS` (60) after firing that got a fill. `leg_update` rows carry no `instrument_id` or `transaction_type`, so both come from the parent's `parent_received` and the leg's `leg_requested`.

## The unresolved stops

19 stops that day had neither. Each was cancelled by the script about a second after firing, and the broker had already filled it: these are the exits the script reported as "the broker shows nothing open, so the stop's order has filled; its price could not be read yet". For example parent 6b7bf82f (trigger 161.25) was broker order 26101900306429, which Flattrade's trade file shows sold at 160.45. The engine stops following an order once cancelled, so its fill never reaches the event log. The broker's order history would have it, but `flattrade.order_updates` has never had a row and `unified.order_updates` has none since 2026-09-29, although `unified-orders@store_orders_to_db` is running; that is a separate fault, not looked into here. Until it is fixed these stops are written with an empty slip and left out of the allowance, which makes the allowance slightly optimistic.

## Checked on 2026-10-19

`bin/unified/orders/stop_slippage --dry-run --date 2026-10-19 --days 7` measured 270 fired stops (269 sell, 1 buy) on nse_equity_index_options: median 18.78 bps, 90th percentile 79.02 bps. On 19 October alone: 110 by the stop, 44 by another order, 19 unresolved, median 16.11 bps, 90th 58.03 bps, and the worst close was 3.60 below a trigger of 185.40.
