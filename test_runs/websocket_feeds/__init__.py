"""Offline recordings of every broker's quotes and order updates websockets.

Each broker has a case file here that drives its two sockets through scripted connections, with the websocket library, Redis, the broker's API class, the clock and the backoff waits replaced by stand-ins.
Every Redis command, every frame sent to the broker, every log line, every login and every wait is kept in the order it happened and compared with `test_runs/fixtures/websocket_feeds.jsonl`.

No Redis, database, credentials or network are used.

Typical usage:

    python -m test_runs.websocket_feeds
    python -m test_runs.websocket_feeds zerodha
    python -m test_runs.websocket_feeds zerodha --record
"""
