"""
Streaming a long result as one JSON array, without holding it.

`/api/instruments/master` and `/api/instruments/ticks` can answer with hundreds of thousands of
objects. The response is still a single JSON array, so any client can parse it, but it is written out
as the rows arrive, in chunks of about 64 KB, rather than built in memory first.

Everything that can fail with a proper status - a bad parameter, an unknown instrument - is checked
before the stream starts. Once it has started the status is already 200, so a failure part way
through is logged and ends the array early rather than producing a different status.
"""

import datetime
import decimal
import json

from flask import Response, stream_with_context

from utilities.configurations import get_logger

logger = get_logger("rest_api.stream")

CHUNK_BYTES = 64 * 1024

_SEPARATORS = (",", ":")

def _default(value):
    """
    JSON spellings for the values database rows and identities carry.

    - `value` is a value `json` cannot encode by itself.
    """
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return str(value)

def json_array_response(items, headers=None):
    """
    A Flask response streaming an iterable of JSON-encodable objects as one JSON array.

    - `items` is an iterable of objects, consumed as the response is sent.
    - `headers` are extra response headers.
    """
    def generate():
        buffer = ["["]
        size = 1
        first = True
        try:
            for item in items:
                encoded = json.dumps(item, default=_default, separators=_SEPARATORS)
                if not first:
                    buffer.append(",")
                    size += 1
                buffer.append(encoded)
                size += len(encoded)
                first = False
                if size >= CHUNK_BYTES:
                    yield "".join(buffer)
                    buffer, size = [], 0
        except Exception:
            logger.exception("a streamed response failed part way; the array was ended early")
        buffer.append("]")
        yield "".join(buffer)

    return Response(stream_with_context(generate()), mimetype="application/json", headers=headers or {})
