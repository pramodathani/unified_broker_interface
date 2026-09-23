"""The order engine: the one process that sends an order to a broker when `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` is `engine`.

An order placed through the engine outlives the HTTP request that asked for it, which is what lets it become a bracket, an OCO pair, a chaser or any other type whose behaviour is a reaction to a later fill, price or clock tick.

`order_intent.py` holds what an API worker writes down, and `intent_handoff.py` holds the writing and the wait for the answer. The engine that reads them is `bin/unified/orders/order_engine`.
"""
