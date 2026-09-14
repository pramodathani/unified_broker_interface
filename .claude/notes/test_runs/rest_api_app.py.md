# Notes on `test_runs/rest_api_app.py`

## The Orders and Portfolio tabs

The Orders tab calls `GET /api/orders/details` and `GET /api/orders/trades`, and the Portfolio tab calls `GET /api/portfolio/funds`, `holdings` and `positions`. All five routes answer from a document that a `bin/unified/` script keeps in Redis, so a call costs one Redis read on the server and never reaches a broker. The page deliberately has no form for `POST /api/orders/place`, the only route that reaches a trading account, so nothing on the page can place an order.

Each endpoint is its own subclass of `UnifiedDocumentView`. The base class holds only the behaviour that is identical for all five: drawing the heading and button, making the call, drawing the `brokers` status table, and two table helpers. Each subclass decides which parts of its document to draw, because the five documents have different shapes: funds has no rows but several figure groups and a per-segment block, positions has two row lists (`net` and `day`), and the other three have one row list and a summary.

## Why the brokers table is drawn on 502 and 503 answers

`unified_broker_interface/utilities/unified_documents.py` sends the `brokers` list, and for a stale document its `as_of`, with its `503` and `502` answers. That list is the quickest way to see which broker script has stopped, so the page draws it whatever the status. The document's own tables are drawn only for a `200`.

## Why figure values are shown as text

`draw_figures` turns a summary dictionary into a two-column table of names and values. The values mix floats, integers and, after flattening, occasionally lists, and a pandas column of mixed types can make Streamlit's Arrow conversion fail. Converting each value with `str` keeps the table readable and avoids that failure.

## Why `show_result` is called with `as_table=True`

For these endpoints the body is a dictionary, so `show_result` draws no table of its own. Passing `as_table=True` only collapses the raw JSON, which keeps a long order book from pushing the tables far down the page.
