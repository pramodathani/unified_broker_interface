# Test runs

`test_runs/` holds the manual scripts: four offline suites, the instrument download runner, the REST API
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

    **`order_routes.py`** - `POST /api/orders/place` and `DELETE /api/orders/cancel` run in-process against an
    in-memory stand-in for Redis, with every broker call answered by a stub. Each of its scenarios keeps the
    HTTP status, the response body, every request that would have reached a broker, headers included, and the
    number of Redis round trips, and the suite compares them with `test_runs/fixtures/order_routes.jsonl`. It
    sends nothing to a broker and needs no Redis, but importing the API reads `.env`. Run it after touching the
    order routes; after an intended change, `--record` rewrites the recording, and the diff of that file is the
    change to review.

    **`connection_warming.py`** - the broker connection idle limit and connection warming, against a local
    HTTP server on 127.0.0.1 that answers warming pings by resetting the connection, closing it straight after
    answering or a moment later, answering with an error or a cookie, or answering too slowly, and that drops
    a request arriving on a connection it has already timed out. Every check requires every order to be
    accepted. It takes about 40 seconds and sends nothing beyond the machine. Run it after touching
    `broker_orders/base.py`, `connection_pool.py` or `connection_warmer.py`.

    ```bash
    python -m test_runs.candle_parse
    python -m test_runs.unified_ticks_sessions
    python -m test_runs.connection_warming
    python -m test_runs.order_routes
    python -m test_runs.order_routes --record   # after an intended change
    ```

=== "Safe - infrastructure"

    **`download_instruments.py`** - downloads the instrument masters into each broker's `instruments`
    table, as `bin/<broker>/instruments` does but without the Redis copy. IND Money's ingester logs in
    through `ensure_session` when no usable token is stored.

    ```bash
    python -m test_runs.download_instruments                 # every broker
    python -m test_runs.download_instruments zerodha dhan    # only these
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
