# `square_off.py`

## Why it cancels before it closes, and what it cancels

A stop or a target still live when its position closes will fill afterwards and open a brand new position the other way, unattended, minutes before the close. That is the same rule the kill switch follows and the Atlas names it directly.

What it cancels is scoped to the instruments being closed, and it finds them in `unified:order-updates` — the hash holding the latest update for every order the whole system has seen. That is deliberately wider than the engine's own legs: an order placed by hand or by another tool is just as capable of re-opening a position, and it is in that hash too.

A cancel a broker refuses is logged and the square-off carries on. Leaving a position open because one stale order could not be cancelled is the worse mistake, since the broker's own square-off is minutes away and will not be as careful.

## Why this is not the flatten route

`POST /api/orders/flatten` is the panic button: everything at every broker, cancelled and closed, behind a confirmation string. This is the opposite in temperament — a scheduled, ordinary end to a day's trading that leaves overnight positions and their protective orders exactly where they are.

The value is the timing and the price. A broker's automatic square-off is a market order into whatever book is there, plus a fee; doing it ten minutes earlier with limit orders is the same trade at a better price.

## The two product vocabularies

`product` in the synthetic block filters positions and is on the vocabulary the REST API **answers** with — `intraday`, `delivery`, `carryforward`. The product the closing orders are sent with comes from the caller's own body and is on the request vocabulary — `MIS`, `CNC`, `NRML`.

Conflating them is not theoretical. The first version set the closing order's product from the position's, and every square-off failed with "product must be one of CNC, MIS, NRML" from inside a clock tick, where nothing was watching. `QuantityReference` already follows the same split for the same reason.

## Why its cancels go through `cancel_outside_order`

`cancel_resting` used to call `placement.cancel` directly. Those cancels reached the broker without taking a rate token and without a row in `unified.synthetic_order_events`, so a square-off cancelling a dozen orders at 15:10 was invisible both to the rate budget and to anyone reading the parent afterwards.

They cannot go through `cancel_leg`, because the orders a square-off cancels are found in `unified:order-updates`, which holds every order in the system, and most of them are not legs of this parent. `cancel_outside_order` in the base class records the cancel against this parent by broker and broker order id, before it is sent and after it is answered, and takes a rate token for that broker first. Replaying those two events changes nothing about the parent, since they describe an order it does not own.

When one of those orders is a leg of another engine parent, the cancel still goes straight to the broker from this parent's thread. The owning parent learns of it from the broker's order update, as it would of any cancel it did not ask for. Handing such cancels to the owning worker belongs to the broker-lane work, where it is part of making modify and cancel aware of the engine.

## Where the closing steps went

Finding the positions, cancelling what rests on them and pricing the closing orders moved to `utilities/position_closer.py`, so `close_on_trigger` can take the same steps. `SquareOff` keeps what is its own: the time, the product and the instruments to close.
