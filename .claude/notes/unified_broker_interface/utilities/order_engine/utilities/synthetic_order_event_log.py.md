# Notes on `unified_broker_interface/utilities/order_engine/synthetic_order_event_log.py`

## Why the write is synchronous and committed before the order is sent

The engine writes a `leg_requested` row and commits it before the broker request leaves the machine. That ordering is the entire basis of recovery: without it, an engine that dies mid-send leaves no evidence that an order may exist at a broker, and the position is discovered only when someone reads the order book by hand.

The cost was measured on 2026-09-23 against the local TimescaleDB, over two hundred writes: a median of 0.527 ms, a 95th percentile of 0.700 ms and a slowest of 2.577 ms. The broker call it precedes takes 100 to 300 ms, so it is under one per cent of the order's cost.

The alternative considered was to `XADD` the event to a stream and drain it to Postgres asynchronously, which would cost about a tenth of a millisecond. It was rejected because it gives recovery two sources of truth that can disagree — the stream may hold rows the table does not — and adds a second daemon whose failure is silent. If the half millisecond ever matters, the stream is the escape hatch, but it should be taken deliberately and not by default.

## Why a UUID is written as text

psycopg2 refuses a `uuid.UUID` with `can't adapt type 'UUID'` unless `psycopg2.extras.register_uuid()` has been called. That registration is global: it changes how every connection in the process adapts values, including the instrument loader's.

Converting to `str` in `row()` is local, explicit and reads the same way at every call site, and PostgreSQL accepts the text form into a `UUID` column without complaint. The cost is one `isinstance` check per value.

## Why the connection is held open and dropped on failure

Opening a connection per event would put a TCP handshake and an authentication round trip on the order path, which is exactly what the measurement above would then be dominated by. So the connection is opened on first use and kept.

A held connection that has failed is worse than none, though, because psycopg2 leaves it in an aborted transaction state where every later statement raises. So any failure closes it and clears it, and the next write opens a fresh one. That turns a transient database restart into one failed order rather than every order until the engine is restarted.

## Why the log keeps a small pool of connections

The log used to hold one connection. psycopg2 does not allow two threads to use one connection at the same time, and with broker lanes many workers write at once, so each write now borrows a connection and gives it back. The pool is limited to `UNIFIED_BROKER_INTERFACE_API_ORDER_DATABASE_CONNECTIONS`, 8 by default, rather than one per worker: the engine can have 300 workers, PostgreSQL's usual connection limit is 100 and is shared with every other script, and each write holds its connection for about half a millisecond, so eight carry thousands of writes a second.

A write that fails closes its connection rather than returning it, which is what forgetting the held connection used to do, and the next write opens a fresh one.
