# Notes on `unified_broker_interface/utilities/broker_quotes/utilities/service.py`

## `quote` is a wrapper over `quotes`

`quote` passes a list of one to `quotes` and raises the entry's `RequestError`, so the single `GET` routes and the `POST` batch share one implementation. The recording in `test_runs/instrument_routes.py` did not change when this replaced the original single-instrument method, including its Redis round trips: one pipeline for the two cached quotes, then the handle read when a broker is needed.

## What a batch costs

- One pipeline holds two `HGET`s per instrument, one on `unified:quotes:live` and one on `unified:quotes:fetched`.
- `order_handles_for_instruments` is called once, for only the instruments whose cached quote is not good enough.
- A broker is asked only for those instruments.

When the quote feeds are running, most instruments are answered from `unified:quotes:live` and never reach a broker. The broker path is for an instrument that nothing has streamed, one whose feed owner went silent (`stale`), or one that has not traded in five minutes while its session is open. That last case is common for far out-of-the-money options.

## Why the broker path uses a thread pool of four

Each broker quote is a blocking HTTPS call, so asking for n quiet instruments one after another adds up n calls. `QUOTE_FETCH_THREADS = 4` lets a batch wait roughly for its slowest group rather than for every call in turn. Four matches the default number of gunicorn threads per worker. It keeps one batch from starting more concurrent calls to a broker than a worker already makes when four single requests arrive together, and brokers refuse bursts well before that becomes a meaningful rate. With exactly one instrument needing a broker, no pool is started, so the single `GET` route runs on the request's own thread as it always did.

Running `_from_broker` on several threads at once was already happening before batches existed, because gunicorn runs four threads per worker and they all share one `QuoteService`. The pieces it touches are built for that: `client_for` creates each broker's client under a lock, the resolver refresh and plan look-up hold `_resolver_lock`, the tick normalizers keep no per-call state, the session gate's window cache only ever stores the same value for a key, and the redis-py client uses a connection pool.

## Where an unexpected error goes

`_from_brokers` catches every exception from one broker, logs it and tries the next broker, and raises a 503 `RequestError` only when all of them failed. `_answer_from_brokers` turns that `RequestError` into the entry's answer. Anything else raised on a pool thread is re-raised by `future.result()` and fails the whole request with a 500, which is the same outcome the single route has always had for an unexpected error.
