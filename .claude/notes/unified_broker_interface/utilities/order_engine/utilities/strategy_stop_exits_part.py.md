# strategy_stop_exits_part.py

## Why only the exits are kept whole (2026-10-02)

The strategy's legs are a basket, which a Together join already places with its margin checked as a group. What no join expresses is a trigger on the whole strategy's profit, and the closes that follow it in a fixed order. So `strategy_stop` is a join preset of the basket and `strategy_stop_exits`, and the exits are the kept-whole part.

## Which instruments it marks

The basket's orders do not price themselves, so the plan would neither watch their instruments nor remember their tick sizes. The reader hands a kept-whole Then child `opened_instruments`, the instrument each of the first plan's orders trades; `instruments()` returns them, so the plan watches their quotes, and `prepared_own_memory` works out their tick sizes before the parent is recorded, refusing one the brokers do not agree on with 503.

## When it is done

Today's type marks its parent `completed` the moment it sends the closes. The part is done only once it has closed and every close has finished, so the plan completes when the position is actually flat. A resting basket order that had not filled when the strategy closed is cancelled by the Then join once a close fills, through `cancel_first_on_child_fill`; today's type leaves it resting.

## Stale quotes, late fills and refused closes (2026-10-05)

A quote marked stale marks nothing, so a stale 900 no longer closes a strategy entered at 1,000. When the stop acts it cancels the basket orders still resting, and `still_open` works out from the legs alone what each filled basket order still needs closed: closes are matched to it by instrument, broker, product and side, and every close counts its whole quantity whatever became of it. Fills that arrive before the cancel lands are closed by `settle`, and the part is done only once nothing of the basket rests. Before, a close was sized to what had filled at that moment and never resized, the basket was cancelled only after a close filled, and a leg that filled afterwards stayed open while the parent read `completed`. A rejected close is not sent again; the Then join records `leaves_open` and the parent ends `failed`.
