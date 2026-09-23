"""The order engine: the one process that sends an order to a broker when `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is `engine`.

An order placed through the engine outlives the HTTP request that asked for it, which is what lets it become a bracket, an OCO pair, a chaser or any other type whose behaviour is a reaction to a later fill, price or clock tick.

`base.py` holds `SyntheticOrder`, the mechanism every order type shares: how a parent is started, how a leg is recorded before it is sent, and how a broker's answer becomes a state change. Each other file at this level holds one order type, `simple.py` being the plain order that is the degenerate case of all of them. `utilities/` holds the intent, the parent order and its legs, the event log, the Redis caches, the single-engine lock and the loop that reads the intent stream.

The daemon that runs all of this is `bin/unified/orders/order_engine`.
"""
