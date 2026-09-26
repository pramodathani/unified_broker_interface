# Notes on `unified_broker_interface/utilities/instrument_batch.py`

## Why a list goes in a `POST` body and not in the query string

Both forms were considered. An instrument named by its fields is several query parameters (`exchange`, `segment`, `symbol` and so on), and nothing in a query string groups the parameters of one instrument apart from the next. A `GET` list would therefore have to be ids only, or a compact key such as Kite's `NSE:INFY`, and gunicorn's default request line limit of 4,094 bytes caps it at roughly 75 ids. A JSON body allows both ways of naming an instrument, mixed, with no length problem. `POST /api/orders/place` already reads an instrument from a JSON body the same way. The user chose `GET` for one instrument and `POST` for a list, on the same path.

## Why the answer's shape follows the method and not the count

A `POST` always answers `{"results": [...]}`, even for a list of one. If the shape changed with the number of instruments instead, every client would need a special case for a list that happened to hold one entry. The `GET` answer is left exactly as it was, so no existing caller is affected.

## Why each entry carries its own status

One unknown instrument should not throw away the other forty-nine answers. Each entry therefore holds the status and message the `GET` form would have given for that instrument, and `data` holds exactly the `GET` object, so code that reads one `GET` answer can read each entry unchanged. Only problems with the request as a whole refuse the whole request: an unreadable body, a bad list, or a bad shared parameter.

`request_index` is included because an instrument named by its fields has no id until it is found, and one that is not found never gets one. Results are matched by position, not by id.

## Why JSON numbers and booleans are turned into text

The query-string parsers in `instrument_identity.py` call `.strip()` on every value, so a JSON number such as `"strike_price": 25000` would raise `AttributeError` and answer 500. `as_text` turns numbers into their text and booleans into `"true"` or `"false"`, which the same parsers already accept. That keeps one set of parsers and one set of error messages for both forms. An object or a list is refused with a message, because there is no text the query string would have had for it.

## Why the limit is 50

The limit bounds how long one request can hold a gunicorn thread and how many broker quote calls one request can cause. Fifty covers a typical watchlist or option chain slice, and it is a constant, `MAX_BATCH_INSTRUMENTS`, so it can be raised in one place.

## The shape of `results` and `valid_instruments`

Items that fail to parse never reach the catalogue. `valid_instruments` hands over only the ones that parsed, and `results` walks the original list and slots each answer back into its position. Keeping that bookkeeping in this class is what lets every blueprint handler stay three lines long.
