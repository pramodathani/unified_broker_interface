# Test runs

`test_runs/` holds the manual scripts: two offline suites, the instrument download runner, the REST API
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

    ```bash
    python -m test_runs.candle_parse
    python -m test_runs.unified_ticks_sessions
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
    session, detail and instrument endpoints by hand, including the 401 paths. Start the API first, then
    `bin/rest-api-app`. A connect replaces the API's one token, so it ends any other client's session.
    The page makes no portfolio or order calls.

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
