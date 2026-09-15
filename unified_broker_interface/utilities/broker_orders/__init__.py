"""How each broker takes and cancels orders, for `POST /api/orders/place` and `DELETE /api/orders/cancel`.

`base.py` holds `BrokerOrders`, the mechanism every broker shares: the checks that decide whether a broker can take an order, the one HTTP call, and the reading of error answers.
Each `<broker>.py` holds one broker's class, which builds that broker's request and reads its success answers, and `noren.py` holds what Flattrade and Shoonya share.
`utilities/` holds the validated requests, the instrument, the request and answer objects and the registry.

Nothing in this package reads Redis, MongoDB or PostgreSQL. The blueprint reads Redis and hands the classes plain dictionaries, so every round trip an order costs stays visible in `unified_broker_interface/blueprints/orders.py`.
"""
