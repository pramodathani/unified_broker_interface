"""
Streaming a long result as one JSON array, or as a batch of results, without holding it.

`/api/instruments/master` and `/api/instruments/ticks` can answer with hundreds of thousands of
objects, and `POST /api/instruments/ticks` with that many for each instrument it names. The response is still one JSON document, so any client can parse it, but it is written out as the rows arrive, in chunks of about 64 KB, rather than built in memory first.

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

def json_results_response(entries, rows_key):
    """
    A Flask response streaming `{"results": [...]}`, in which an entry may carry a streamed array of rows.

    Each entry is written as soon as it is reached, and its rows, when it has any, are written inside it under `rows_key` as they arrive, so a batch of long series is never held in memory. A failure part way through is logged, and the open arrays and objects are closed so the answer stays valid JSON.

    Args:
        entries (Iterable[tuple[dict, Iterable | None]]): Pairs of a non-empty result entry and the rows to stream under `rows_key` inside it, or None for an entry without rows, consumed as the response is sent.
        rows_key (str): The key the rows are written under, such as "ticks".

    Returns:
        flask.Response: The streaming response.
    """
    def generate():
        buffer = ['{"results":[']
        size = len(buffer[0])
        first_entry = True
        inside_rows = False
        try:
            for entry, rows in entries:
                if not first_entry:
                    buffer.append(",")
                    size += 1
                first_entry = False
                encoded = json.dumps(entry, default=_default, separators=_SEPARATORS)
                if rows is None:
                    buffer.append(encoded)
                    size += len(encoded)
                    continue
                opening = encoded[:-1] + "," + json.dumps(rows_key) + ":["
                buffer.append(opening)
                size += len(opening)
                inside_rows = True
                first_row = True
                for row in rows:
                    encoded_row = json.dumps(row, default=_default, separators=_SEPARATORS)
                    if not first_row:
                        buffer.append(",")
                        size += 1
                    buffer.append(encoded_row)
                    size += len(encoded_row)
                    first_row = False
                    if size >= CHUNK_BYTES:
                        yield "".join(buffer)
                        buffer, size = [], 0
                buffer.append("]}")
                size += 2
                inside_rows = False
                if size >= CHUNK_BYTES:
                    yield "".join(buffer)
                    buffer, size = [], 0
        except Exception:
            logger.exception("a streamed response failed part way; the results were ended early")
            if inside_rows:
                buffer.append("]}")
        buffer.append("]}")
        yield "".join(buffer)

    return Response(stream_with_context(generate()), mimetype="application/json")
