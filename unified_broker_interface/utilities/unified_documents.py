"""
Reading the documents the `bin/unified/` scripts keep in Redis, for the routes that answer from them.

`bin/unified/funds`, `holdings`, `positions`, `orders` and `trades` each combine every broker's data into one document
in the REST API's own shape and write it to a Redis key - every half second, or every minute for holdings. A route
answers with that document rather than asking every broker while the client waits. The document carries `as_of`, when
it was written, and `brokers`, how each broker's data was read.

A document is not served when it cannot be trusted:

- missing or unreadable - its script is not running, or has never run - is `503`;
- older than the route allows - its script has stopped - is `503`, with the document's `as_of` and `brokers`, so a client
  never mistakes an old book for today's;
- read, but with no broker's data in it - every broker `missing` or `unreadable` - is `502`, as when no broker could be
  read live, still listing each broker's status.

A `stale` broker's data is still in the document, so it counts as read, and its status says how old it is.
"""

import json
from datetime import datetime

# The `as_of` format every unified document is written with, in the machine's local time.
AS_OF_FORMAT = "%Y-%m-%dT%H:%M:%S"

# The broker statuses whose data a document includes.
READ_STATUSES = {"ok", "stale"}

def read_document(cache, key, max_age_seconds, subject, now=None):
    """
    A unified document and the HTTP status to answer with, as `(body, status)`.

    - `cache` is the Redis client.
    - `key` is the Redis key the document is kept in.
    - `max_age_seconds` is the oldest `as_of` still served.
    - `subject` names what the document holds, for the error messages, such as `funds`.
    - `now` is the current local time; the clock when None.
    """
    try:
        value = cache.get(key)
        document = json.loads(value) if value is not None else None
    except Exception:
        document = None
    if not isinstance(document, dict):
        return {'error': f'{subject.capitalize()} are not available: nothing is keeping {key}'}, 503

    brokers = document.get('brokers') or []
    try:
        as_of = datetime.strptime(document.get('as_of'), AS_OF_FORMAT)
    except (TypeError, ValueError):
        as_of = None
    now = now or datetime.now()
    if as_of is None or (now - as_of).total_seconds() > max_age_seconds:
        return {'error': f'{subject.capitalize()} are out of date: {key} was last written at {document.get("as_of")}',
                'as_of': document.get('as_of'), 'brokers': brokers}, 503

    if not any(isinstance(broker, dict) and broker.get('status') in READ_STATUSES for broker in brokers):
        return {'error': f'Unable to retrieve {subject} information', 'brokers': brokers}, 502
    return document, 200
