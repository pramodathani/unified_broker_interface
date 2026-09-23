# Test runs

`test_runs/` holds the manual scripts: the offline suites, the instrument download runner, the REST API
test page, and a login check against the live brokers.

!!! warning "`broker_login_test.py` logs in to live broker accounts"

    It constructs the broker API classes, which log in with the credentials stored in MongoDB. It places
    no orders.

    Every script in the directory has an `if __name__ == "__main__"` guard, so importing one is safe.

## What is in the directory

=== "Safe - offline"

    **`candle_parse.py`** - the seven historical candle parsers, replayed against payloads recorded from
    the live APIs. No credentials, no network, no market session. The suite to run after touching a
    candle parser.

    **`unified_ticks_sessions.py`** - the session gate against the exchanges' trading calendars in
    `stock_brokers/instruments/ticks/utilities/calendars/`, checked against dates the exchanges' own
    publications state. Needs no Redis, no database and no broker. Run it after adding or amending a
    year's calendar.

    **`order_routes.py`** - `POST /api/orders/place`, `PUT /api/orders/modify` and `DELETE /api/orders/cancel` run in-process against an
    in-memory stand-in for Redis, with every broker call answered by a stub. Each of its scenarios keeps the
    HTTP status, the response body, every request that would have reached a broker, headers included, and the
    number of Redis round trips, and the suite compares them with `test_runs/fixtures/order_routes.jsonl`. It
    sends nothing to a broker and needs no Redis, but importing the API reads `.env`. Run it after touching the
    order routes; after an intended change, `--record` rewrites the recording, and the diff of that file is the
    change to review.

    **`order_engine_routes.py`** - `POST /api/orders/place` run the same way but with
    `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT` set to `engine`, so the route writes the order to
    `unified:orders:intents:stream` and waits instead of calling a broker. The engine is replaced by an answer
    seeded onto the reply list before the request is sent, and the stand-in's `blpop` returns None rather than
    waiting, so the timeout path costs no time. Each scenario keeps the HTTP status, the body, the intents that
    reached the stream and the Redis round trips, and compares them with
    `test_runs/fixtures/order_engine_routes.jsonl`.

    It has its own recording on purpose. `--record` rewrites a whole fixture, so putting these scenarios in
    `order_routes.jsonl` would silently rewrite the recording that proves the direct path never changed.

    **`order_engine.py`** - `bin/unified/orders/order_engine` itself, driven through its own classes with
    scripted intents on the stand-in's stream and every broker call stubbed. Its loop normally blocks for new
    entries and runs until stopped, so the suite hands it a stop event that allows a fixed number of passes
    and then reports that it should stop, which makes one deterministic pass over the stream. Each scenario
    keeps what the engine pushed onto the waiting worker's reply key, every broker request, whether the intent
    was acknowledged, the engine's counters and the Redis round trips, and compares them with
    `test_runs/fixtures/order_engine.jsonl`. The single-engine lock is checked directly, because losing it
    depends on a clock the loop owns.

    **`order_flatten.py`** - `POST /api/orders/flatten`, the panic button, run in-process against the same
    stand-in with every broker call stubbed. Each scenario keeps the status, the body, every broker request **in the
    order it was sent** and the Redis round trips, and compares them with `test_runs/fixtures/order_flatten.jsonl`.
    The ordering is the point: a cancel appearing after a close would change the recording, and that ordering is the
    whole reason the route exists. The brokers' order books report the cancelled orders as `CANCELLED` from the second
    read onward, which is what the pollers do a moment after a cancel lands; a scenario can leave them open instead,
    to check what the route says when a cancel is never confirmed.

    **`connection_warming.py`** - the broker connection idle limit and connection warming, against a local
    HTTP server on 127.0.0.1 that answers warming pings by resetting the connection, closing it straight after
    answering or a moment later, answering with an error or a cookie, or answering too slowly, and that drops
    a request arriving on a connection it has already timed out. Every check requires every order to be
    accepted. It takes about 40 seconds and sends nothing beyond the machine. Run it after touching
    `broker_orders/base.py`, `connection_pool.py` or `connection_warmer.py`.

    **`contract_sizes.py`** - the rule that decides whether a currency or commodity contract's size is trusted,
    run on made-up source figures. Run it after touching
    `stock_brokers/instruments/mapping/utilities/contract_sizes.py`.

    **`price_cache.py`** - the Redis copy of candles `/api/instruments/prices` serves, run against a
    stand-in Redis that keeps its keys in a dictionary. It checks that a stored copy is sliced for a
    sub-range, that a request reaching past the copy reads the union of the two ranges, that the union is
    refused when it would outgrow the intraday span, and that a copy is thrown away when the price
    history loader has run since, when the columns differ, or when it is too large to keep. Needs no
    Redis, database or network. Run it after touching
    `unified_broker_interface/utilities/price_cache.py` or the `/prices` route.

    **`virtual_queue.py`** - the queue estimate behind the synthetic limit order book, fed scripted sequences of
    quotes: joining behind the visible depth, trades at and through the price, cancellations ahead, arrivals behind,
    a price beyond five levels, a change of owning broker, a stale quote, a new session, the other side reaching the
    price, and the sell side. The virtual book that keeps the estimates is run against a stand-in Redis. Needs no
    Redis, database or network. Run it after touching `virtual_queue.py` or `virtual_book.py`.

    ```bash
    python -m test_runs.candle_parse
    python -m test_runs.virtual_queue
    python -m test_runs.contract_sizes
    python -m test_runs.price_cache
    python -m test_runs.unified_ticks_sessions
    python -m test_runs.connection_warming
    python -m test_runs.order_routes
    python -m test_runs.order_routes --record   # after an intended change
    python -m test_runs.order_engine_routes
    python -m test_runs.order_engine_routes --record
    python -m test_runs.order_engine
    python -m test_runs.order_engine --record
    python -m test_runs.order_flatten
    python -m test_runs.order_flatten --record
    ```

=== "Safe - infrastructure"

    **`download_instruments.py`** - downloads the instrument masters into each broker's `instruments`
    table, as `bin/<broker>/instruments/daily_feed` does but without the Redis copy. IND Money's ingester logs in
    through `ensure_session` when no usable token is stored.

    ```bash
    python -m test_runs.download_instruments                 # every broker
    python -m test_runs.download_instruments zerodha dhan    # only these
    python -m test_runs.download_instruments --bootstrap zerodha  # replace today's snapshot
    ```

=== "Safe - web page"

    **`rest_api_app.py`** - a Streamlit page (port 8501) for calling the [REST API](rest-api.md)'s
    session, detail, order book, portfolio and instrument endpoints by hand, including the 401 paths.
    Start the API first, then `bin/rest-api-app`. A connect replaces the API's one token, so it ends any
    other client's session. The Orders tab reads `/api/orders/details` and `/api/orders/trades`, and the
    Portfolio tab reads funds, holdings and positions.

=== "Live accounts"

    **`broker_login_test.py`** - constructs the API classes of the brokers left uncommented in `main()`,
    which logs each one in. See the warning above.

The live stream and persister runners are the scripts in `bin/<broker>/`; see
[Broker scripts](broker-scripts.md).

## Testing after hours

NSE and BSE equity close at 15:30 IST, so an equity subscription after that connects and sits
idle - which still exercises connect, subscribe and shutdown, but proves nothing about parsing.
MCX commodity futures trade until 23:30, so they are what to subscribe to for an evening test - with
a broker's `quotes` script and `--tokens`, or its subscription set. See
[Adding a subscription](broker-scripts.md#adding-a-subscription).
