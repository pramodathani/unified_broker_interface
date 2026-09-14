-- Live ticks for every unified instrument, one table across all brokers.
--
-- Written by bin/unified/persist_ticks from the unified quote stream bin/unified/quotes fills. Each row is one quote the
-- unified quote layer accepted: resolved to its unified.instruments id, from the broker that owned the instrument at
-- that moment, normalized so a row means the same thing whichever broker it came from - prices in rupees on the tick
-- grid, previous_close the previous session's close with change_percent recomputed from it, quantities in underlying
-- units with lot_size recording the multiplier, and times as true UTC instants, NULL where a broker does not send them
-- reliably.
--
-- The same order book layout as the per-broker tick tables: five bid and five ask levels flattened into columns, best
-- level first, because columnar compression works on repeated numerics and barely helps JSON.
--
-- The unified schema is created by the mapping DDL; the line below only makes this file safe to apply on its own.

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.ticks (
    -- When the broker feed decoded the tick. Always present, and the one clock every broker shares.
    "time"              TIMESTAMPTZ    NOT NULL,
    instrument_id       UUID           NOT NULL,
    -- The broker that owned the instrument when this tick was written.
    broker              TEXT           NOT NULL,
    exchange_time       TIMESTAMPTZ,
    last_trade_time     TIMESTAMPTZ,
    last_price          NUMERIC(18,4),
    last_quantity       BIGINT,
    average_price       NUMERIC(18,4),
    volume              BIGINT,
    buy_quantity        BIGINT,
    sell_quantity       BIGINT,
    open                NUMERIC(18,4),
    high                NUMERIC(18,4),
    low                 NUMERIC(18,4),
    previous_close      NUMERIC(18,4),
    change_percent      NUMERIC(12,4),
    oi                  BIGINT,
    oi_day_high         BIGINT,
    oi_day_low          BIGINT,
    lot_size            INTEGER,
    bid1_price NUMERIC(18,4), bid1_quantity BIGINT, bid1_orders INTEGER,
    bid2_price NUMERIC(18,4), bid2_quantity BIGINT, bid2_orders INTEGER,
    bid3_price NUMERIC(18,4), bid3_quantity BIGINT, bid3_orders INTEGER,
    bid4_price NUMERIC(18,4), bid4_quantity BIGINT, bid4_orders INTEGER,
    bid5_price NUMERIC(18,4), bid5_quantity BIGINT, bid5_orders INTEGER,
    ask1_price NUMERIC(18,4), ask1_quantity BIGINT, ask1_orders INTEGER,
    ask2_price NUMERIC(18,4), ask2_quantity BIGINT, ask2_orders INTEGER,
    ask3_price NUMERIC(18,4), ask3_quantity BIGINT, ask3_orders INTEGER,
    ask4_price NUMERIC(18,4), ask4_quantity BIGINT, ask4_orders INTEGER,
    ask5_price NUMERIC(18,4), ask5_quantity BIGINT, ask5_orders INTEGER
    -- No primary key: two ticks for one instrument can share a microsecond, and a key violation would fail a whole COPY.
    -- No foreign key to unified.instruments either: a check paid on every row of a hypertable load.
);

-- A trading day of ticks in one chunk, the unit most queries scan and the unit compression and retention act on.
SELECT create_hypertable(
    'unified.ticks',
    by_range('time', INTERVAL '1 day'),
    if_not_exists => TRUE
);

-- Almost every query is "this instrument, over this period", most recent first.
CREATE INDEX IF NOT EXISTS ticks_instrument_time_idx
    ON unified.ticks (instrument_id, "time" DESC);

ALTER TABLE unified.ticks SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'instrument_id',
    timescaledb.orderby = '"time" DESC'
);

-- The current week stays uncompressed for fast ad hoc querying, as for the broker tick tables.
CALL add_columnstore_policy(
    'unified.ticks',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);
