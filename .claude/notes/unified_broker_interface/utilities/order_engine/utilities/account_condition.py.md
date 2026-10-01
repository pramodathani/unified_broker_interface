# Notes on `unified_broker_interface/utilities/order_engine/utilities/account_condition.py`

## Why it copies the account-conditional type's rules

The three figures, their sources (`unified:portfolio:funds` for margin and profit, the combined positions for the count) and the required direction are those of `account_conditional.py`. The offline scenarios `a_plan_account_conditional_order_*` send the same requests as today's.

## Why it needs no prices

It reads Redis, not quotes, so `needs_prices` is false, which puts it among the triggers clock ticks fire. Today's type is checked on the price ticker's clock, about once a second; so is this.

## Cancelling on a condition

Today's `action: cancel` sends the order and cancels it when the figure reaches the level. In a plan that is a lifetime ending `when` the condition holds, the design's last lifetime kind, which `OrderPart.end_lifetime` checks on every tick for a part whose record says `ends_when`.
