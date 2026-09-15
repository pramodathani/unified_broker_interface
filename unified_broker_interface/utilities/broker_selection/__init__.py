"""How `POST /api/orders/place` decides which broker to try first.

`base.py` holds `BrokerSelector`, the interface every selection algorithm implements. Each other module holds one algorithm, and `utilities/registry.py` lists them by name. `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR` names the one a worker uses.

A selector only orders the brokers. Whether a broker can take the order is decided afterwards by its `BrokerOrders` class, and a selector never reads Redis itself: it queues the commands it needs on the blueprint's pipeline and is handed their replies.
"""
