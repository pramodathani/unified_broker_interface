# Notes on `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py`

## Why it exists

Some brokers refuse every order past a fixed number a day. It came up while designing the synthetic limit order book, whose whole purpose is to spend fewer of those orders, and nothing in the engine counted them: `OrderToTradeRatio` counts sends, but only in memory, so it starts again at every restart, and it never refuses anything.

The caps found on 2026-09-23 were Zerodha at 3,000 a day across every platform (Kite's documentation says 5,000, and the forum answer is the more recent statement), Dhan at 7,000, Shoonya saying there is none, and the other seven publishing none. Zerodha counts placements only, rejections included; modifies and cancels do not count. Whether Dhan counts modifies was not found.

## Why part of the cap is kept for exits

At Zerodha, once the cap is reached, even the order that closes a position is refused. A count that let entries run right up to the cap could leave an open position that cannot be closed until support raises the limit. So entries stop at `cap - int(cap * exit_reserve)`, and exits may continue to the cap itself. The default reserve is 5 per cent: 150 orders of Zerodha's 3,000.

## How a leg is judged to be an exit

Roles do not say it cleanly. `stop`, `target`, `close` and `backstop` are always exits, but a hidden stop fires through `PriceTrigger.fire`, which names every leg `entry`, so `HiddenStop` sets `CLOSES_POSITIONS` and `CandleCloseStop` inherits it. A plain order has no way of knowing whether it opens or closes a position, so the caller says so with `closes_position: true` in the `synthetic` object. Without that flag a manual exit near the cap is refused as an entry, which is the safer mistake.

## Why it lives in Redis, one key per broker

It must survive a restart, because an engine restarted at two in the afternoon has not been sent zero orders that day. One string key per broker, incremented and given an `EXPIREAT` of the next 06:00 IST in one pipeline, matches the reset every other engine key uses. The 06:00 arithmetic is repeated here rather than borrowed from `ParentStore.reset_epochs`, which answers a slightly different question (the latest reset as well as the next) and belongs to the parent cache.

## Why it fails open

A count that cannot be read does not refuse, for the same reason `LossLockout` does not: Redis being briefly unreadable should not become an outage of its own. A count that cannot be written leaves the day short by one, and says so at warning.

## Where the check sits

`SyntheticOrder.place_leg` calls `RiskGates.refuse_if_capped` right after `EnginePlacement.prepare` has chosen the broker and before `leg_requested` is recorded, so a refused order leaves no leg in the event log. The parent is then marked `rejected` by the ordinary refusal path, which the offline scenarios record.
