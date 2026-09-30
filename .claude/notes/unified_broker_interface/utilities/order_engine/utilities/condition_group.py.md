# Notes on `unified_broker_interface/utilities/order_engine/utilities/condition_group.py`

## Why every member is asked on every tick

With `all`, stopping at the first member that says no would leave a later member's `double_last` or `held` count stale, so the group would behave differently depending on member order. Asking every member keeps each one's memory current.

## Why members keep memory under their position

Two `held` conditions in one group must count their own time. The group hands each member the dictionary under its index, so members never share or overwrite each other's memory. The positions come from the caller's list, which is stored unchanged, so they are stable across restarts.
