# Notes on `test_runs/reset_recovery.py`

Added on 2026-10-21 with the reset recovery in `BrokerOrders.send_place` and `NorenOrders.find_placed_order`.

The local server resets a connection with `SO_LINGER` 0 after reading the request, as `connection_warming.py` does for pings. Locally the client usually sees that as `RemoteDisconnected` rather than `ConnectionResetError`; both count as resets, and the check `only resets count as resets` covers Flattrade's real form separately with a constructed error.

`reset_before` reads the request and resets without recording it, which is what Flattrade did on 19 and 21 October 2026. `reset_after` records the order and then resets, the case in which a blind resend would have placed it twice; the check requires the book's order id and a single `PlaceOrder`.

The suite does not import `utilities.configurations`, so it needs no `.env`, and it takes about 4.5 s, mostly the one-second timeouts of the reset-the-book case.
