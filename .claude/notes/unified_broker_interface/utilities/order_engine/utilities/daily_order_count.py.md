# Notes on `unified_broker_interface/utilities/order_engine/utilities/daily_order_count.py`

## Why it exists

Some brokers refuse every order past a fixed number a day. It came up while designing the synthetic limit order book, whose whole purpose is to spend fewer of those orders, and nothing in the engine counted them: `OrderToTradeRatio` counts sends, but only in memory, so it starts again at every restart, and it never refuses anything.

The caps found on 2026-09-23 were Zerodha at 5,000 a day (Kite's documentation; a 2023 forum answer said 3,000 across every platform, and the account holder confirmed 5,000 on 2026-09-24), Dhan at 7,000, Shoonya saying there is none, and the other seven publishing none. A forum answer said Zerodha counts placements only, but the account holder said on 2026-09-24 that the caps they meant count placements, modifications and cancellations alike, so every message is counted for every capped broker.

On 2026-09-24 every broker's own API documentation was read. Dhan's 7,000 is on the DhanHQ v2 home page, in one "Order APIs" bucket that probably includes modifies. Fyers' "Regulatory Changes (April 2026)" page caps transactional requests at 10,000 a day and explicitly counts modify, cancel and exit, which this class does not: it counts in `count_sent`, which only placements reach. Shoonya states there is no daily limit. The other six state none. The full table is in `docs/get-started/configuration.md`.

## Why part of the cap is kept for exits

At Zerodha, once the cap is reached, even the order that closes a position is refused. A count that let entries run right up to the cap could leave an open position that cannot be closed until support raises the limit. So entries stop at `cap - int(cap * exit_reserve)`, and exits may continue to the cap itself. The default reserve is 5 per cent: 250 orders of Zerodha's 5,000.

## How a leg is judged to be an exit

Roles do not say it cleanly. `stop`, `target`, `close` and `backstop` are always exits, but a hidden stop fires through `PriceTrigger.fire`, which names every leg `entry`, so `HiddenStop` sets `CLOSES_POSITIONS` and `CandleCloseStop` inherits it. A plain order has no way of knowing whether it opens or closes a position, so the caller says so with `closes_position: true` in the `synthetic` object. Without that flag a manual exit near the cap is refused as an entry, which is the safer mistake.

## Why it lives in Redis, one key per broker

It must survive a restart, because an engine restarted at two in the afternoon has not been sent zero orders that day. One string key per broker, incremented and given an `EXPIREAT` of the next 06:00 IST in one pipeline, matches the reset every other engine key uses. The 06:00 arithmetic is repeated here rather than borrowed from `ParentStore.reset_epochs`, which answers a slightly different question (the latest reset as well as the next) and belongs to the parent cache.

## Why it fails open

A count that cannot be read does not refuse, for the same reason `LossLockout` does not: Redis being briefly unreadable should not become an outage of its own. A count that cannot be written leaves the day short by one, and says so at warning.

## Where the check sits

`SyntheticOrder.place_leg` calls `RiskGates.refuse_if_capped` right after `EnginePlacement.prepare` has chosen the broker and before `leg_requested` is recorded, so a refused order leaves no leg in the event log. The parent is then marked `rejected` by the ordinary refusal path, which the offline scenarios record.

## Why counting moved into `BrokerOrders.send`

The first version counted in `RiskGates.count_sent`, which only placements reach, and only in the engine. Once the user made clear that modifies and cancels count, that missed three paths: the engine's own `reprice_leg`, `reduce_leg` and `cancel_leg`, and the REST API's direct `modify`, `cancel` and `flatten` routes, which never pass through the engine. Every one of them ends in `BrokerOrders.send`, so the count is kept there, attached to each broker's order class by `OrderPlacement.attach_daily_count` in both the engine and each API worker. A request whose connection could not be made is not counted; anything the broker could have seen is.

Only capped brokers are counted, which also keeps the offline route recordings unchanged: their configuration names no caps, so no request costs an extra Redis call.

## What is refused, and what never is

Refusing still happens only in the engine, where `refuse_if_capped` is asked before a placement (`place_leg`) and before a price change (`SyntheticOrder.has_room_today`, from `reprice_leg`). An entry's re-price stops where new entries stop; an exit's may use the reserve. `cancel_leg` and `reduce_leg` are never asked, because refusing a cancel could leave an unwanted order live, which is worse than exceeding a cap that the broker will enforce anyway.
