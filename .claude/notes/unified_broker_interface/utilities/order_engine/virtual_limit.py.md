# Notes on `unified_broker_interface/utilities/order_engine/virtual_limit.py`

## Where the idea came from

In the session that built the order types, the user asked whether limit orders could be kept in a simulated book and only sent when likely to fill, because several brokers cap the number of orders a day. The first suggested release rule, "send when the price is within the top two levels of the bid", was rejected in discussion: a passive order sent late joins the back of the queue and is no more likely to fill. The rule chosen on 2026-09-23 is to send when the **opposite** touch reaches the price, which fills immediately at the caller's price and spends exactly one order per fill. The queue estimate from `virtual_book` then measures what that rule misses.

## Why it is a `PriceTrigger`

It is `LimitIfTouched` with the watched price being the opposite touch and the limit and trigger being the same number. Everything else a trigger needs (answering `202 armed`, firing once, `has_fired` surviving a restart, `remember_tick_size`) was already there.

## Why the limit price is the body's own `price`

`LimitIfTouched` takes `limit_price` separately because its trigger and limit differ. Here they are the same, so the body is just an ordinary limit order with `synthetic.type` added, and a caller can switch an existing limit order to a held one by adding one field. A body that is not `LIMIT` with a price is refused with 400 before anything is recorded.

## Why it does not carry overnight

The plan said `CARRIES_OVERNIGHT`. It was left off deliberately: an exchange DAY limit dies at the close, and a held order that silently came back the next morning would surprise anyone used to that. Recovery reads today's events, so a restart during the day resumes the order, which is what the user asked for ("stay held, resume on restart"). A held order past 06:00 drops out of the open set without a terminal event, the same as every other day-only trigger type.

## Why nothing is sent on shutdown

The earlier session proposed pushing every held order to the exchange on SIGTERM. The user chose instead to keep them held and resume on restart, because sending them would spend the daily orders the type exists to save. The danger admonition on `virtual_limit` in `docs/rest-api/synthetic-orders.md` says what that costs.

## Paper fills

A paper order never calls `place_leg`, so it takes no rate token and is not counted against any daily cap. Its fills are `paper_filled` events carrying the cumulative `filled_quantity`, replayed by `ParentOrder.apply_paper_fill` into `parameters['paper_filled']`, so a restart neither loses nor repeats a fill. The parent goes `received` to `working` on the first fill and `working` to `completed` on the last, which are both allowed changes. Every paper fill is priced at the limit, even one caused by the opposite touch coming through the price, where a real order could have done better; the estimate does not record the price the other side reached.

## `missed_quantity` is kept in Redis only

It is written into the parameters and saved with the parent, like `triggered_at`, but not into the event log. The status message of the state change that follows firing does not carry it either. A restart after firing loses it from the parent document, while the estimate itself remains in `unified:orders:virtual_queue` until the parent closes.
