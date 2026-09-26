# Notes on `unified_broker_interface/utilities/instrument_catalogue.py`

## One code path for one instrument and for many

`resolve`, `details` and `additional_details` are thin wrappers over `resolve_many`, `details_many` and `additional_details_many`. They pass a list of one and raise that entry's error, if it has one. There is deliberately no second, single-instrument implementation, so the `GET` routes and the `POST` batch routes cannot drift apart. `test_runs/instrument_routes.py` recorded the single routes before the list versions existed, and the recording did not change when the wrappers replaced the originals, which includes the number of Redis round trips.

## How a list is resolved in a fixed number of round trips

- The mapping date and segment counts are read once for the whole list, since every instrument is answered on the same date.
- Instruments named by id need no catalogue look-up.
- Instruments named by their identity fields each need a `ZRANGEBYLEX` on their segment's catalogue. `MappingRedisTier.read_catalogue_for_prefixes` sends all of them in one pipeline.
- Every id found either way is read from the identity hash with one `HMGET`.
- `details_many` then reads seen dates and handles for all cached instruments with one `HMGET` each, and `additional_details_many` reads attributes with one `HMGET`, plus one `EXISTS` only when some came back empty.

A list of one costs exactly what the single routes cost before, because each step is skipped when it has nothing to do. For example, the prefix pipeline is not sent when every instrument was named by id.

## Why the Postgres fallbacks stay one instrument at a time

`_resolve_from_postgres` and `MappingResolver.broker_rows_on_date` still run once per instrument. They are reached only for a past `date`, a cold cache, or the history of an instrument no longer mapped. Batching them would mean one SQL statement matching a mix of ids and differently shaped identity fields, through a `VALUES` join. That statement would be harder to read and to keep in agreement with the cached answer, for paths that are rare by design. The additional attributes fallback is the exception, because `MappingPostgresTier.read_additional_attributes` already took a list.

## Why an entry is either a result or a `RequestError`

Each list method returns one entry per instrument, in request order, and an entry that failed holds the `RequestError` that the single route would have raised. The blueprint turns that error into the entry's `status` and `error`, with the same message and status the single route gives. Errors about the whole request, such as nothing having been mapped yet, are still raised, because no entry could be answered.
