# Notes on `unified_broker_interface/utilities/order_engine/account_conditional.py`

## Why it is a price trigger

The shape is a price trigger's: record the order, answer `202 armed`, compare a figure with a level once a second, and fire once. Only the figure differs, so `watched_price` returns the account figure instead of a price, and the base class's comparison, `triggered_at` bookkeeping and firing all apply unchanged. `TAKES_TRIGGER_ON` is False because `trigger_on` chooses between prices.

## Why the day's profit is read from the funds document

`LossLockout` reads realized plus unrealized profit from `unified:portfolio:funds`. Reading the same figure the same way means a condition on the day's loss and the lockout can never disagree about where the account stands.

## Why `action: cancel` has its own tick handling

The base `on_price_tick` stops once a parent has legs, because a price trigger that has placed its child has fired. A cancel-mode order places its leg at once, so it watches the condition in its own branch of `on_price_tick` and cancels that leg.

## What was not built

The Atlas's G17 also lists conditions on traded volume, the day's percentage change and another order's execution. Volume and percentage change are properties of a quote, which `indicator_triggered` already watches; another order's execution is what `oto` does. This type covers the account's own state, which nothing else did.
