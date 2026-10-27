"""
How each broker's quote websocket names an instrument in its Redis subscription set.

`bin/unified/instruments/allocate_subscriptions` gives each of the day's unified instruments to one broker and writes it into that broker's `<broker>:quotes:subscriptions` set, which the broker's `bin/<broker>/instruments/websocket_quotes` subscribes. Every broker spells a member differently - Kite's bare token, Dhan's `NSE_FNO:35000`, Noren's `NFO|35000`, a Fyers symbol - so one module per broker turns a mapping row into that spelling. `base.py` defines what a module provides, and `utilities/registry.py` lists them.
"""
