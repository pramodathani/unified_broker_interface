-- Every order transition at every broker, one table across all brokers.
--
-- Written by bin/unified/persist_orders from the unified order update stream bin/unified/order_updates fills. Each row
-- is one update a broker's order websocket delivered, normalized to the REST API's order contract - status, side,
-- product, order type and validity on the shared vocabulary, times as instants - and resolved to its
-- unified.instruments id where the unified cache names one. The table is an append-only audit trail rather than a
-- current-state table: an order that changed state five times is five rows, so its whole history can be read back.
--
-- `time` is when the broker's own script received the update. `exchange` stays the broker's own code, as the order
-- contract has it; `instrument_id` is the instrument it resolved to, or NULL. `raw` is reserved for the broker's
-- untouched payload and is NULL while the unified stream does not carry it.
--
-- The unified schema is created by the mapping DDL; the line below only makes this file safe to apply on its own.

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.order_updates (
    "time"              TIMESTAMPTZ    NOT NULL,
    broker              TEXT           NOT NULL,
    order_id            TEXT           NOT NULL,
    exchange_order_id   TEXT,
    parent_order_id     TEXT,
    status              TEXT,
    status_message      TEXT,
    id                  TEXT,
    instrument_id       UUID,
    instrument_token    TEXT,
    tradingsymbol       TEXT,
    exchange            TEXT,
    transaction_type    TEXT,
    product             TEXT,
    order_type          TEXT,
    validity            TEXT,
    quantity            BIGINT,
    filled_quantity     BIGINT,
    pending_quantity    BIGINT,
    cancelled_quantity  BIGINT,
    disclosed_quantity  BIGINT,
    price               NUMERIC(18,4),
    trigger_price       NUMERIC(18,4),
    average_price       NUMERIC(18,4),
    order_timestamp     TIMESTAMPTZ,
    exchange_timestamp  TIMESTAMPTZ,
    tag                 TEXT,
    raw                 JSONB
    -- No primary key: a transition delivered twice is two rows, which a key violation would turn into a failed COPY.
);

-- Order updates are sparse beside ticks - hundreds a day rather than millions - so a month to a chunk keeps chunks from
-- being mostly overhead.
SELECT create_hypertable(
    'unified.order_updates',
    by_range('time', INTERVAL '1 month'),
    if_not_exists => TRUE
);

-- The query that matters: every transition of one order at one broker, most recent first.
CREATE INDEX IF NOT EXISTS order_updates_broker_order_time_idx
    ON unified.order_updates (broker, order_id, "time" DESC);

CREATE INDEX IF NOT EXISTS order_updates_instrument_time_idx
    ON unified.order_updates (instrument_id, "time" DESC);

ALTER TABLE unified.order_updates SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'broker, order_id',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'unified.order_updates',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);
