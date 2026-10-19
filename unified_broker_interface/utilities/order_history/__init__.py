"""A lasting record of every broker's orders, kept after Redis forgets them.

Each broker's orders live in Redis only for the day: `<broker>:orders:orders` and the combined `unified:orders:orders` expire at the next 06:00 IST. Order update streams reach the database for the brokers that stream them, but Flattrade's orders are only ever polled, so nothing kept them. `daily_order_snapshot.py` saves every order's final state for the day to `unified.daily_orders`, and `bin/unified/orders/store_daily_orders` runs it every weekday night.
"""
