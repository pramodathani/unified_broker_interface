# Notes on `stock_brokers/instruments/mapping/utilities/sql/ddl/130_unified_contract_sizes.sql`

`unified.contract_sizes` holds one row per live currency and commodity derivative per mapping date: the decided `units_per_lot` in quotation units, the decision's `status`, whether orders may be sent (`tradeable`), and every source's figure in `sources` as JSON. `contract_sizes.py` replaces a date's rows each run.

It is dated, like `unified.broker_mappings`, because exchanges revise lot sizes, and a decision has to be read back for the day it was made. It is a hypertable by `mapping_date` for the same reason the mappings are.

The table deliberately has no foreign key to `unified.instruments`. `utilities/collisions.py` merges stale duplicate instruments away on later runs, and a foreign key from older dated rows would make such a merge fail, or tie the merge to a table it has no reason to know about. Readers join on `instrument_id` anyway.

`segment` is stored beside the instrument so the daily summary and the index on `(mapping_date, segment, status)` can count decisions without joining the master table.
