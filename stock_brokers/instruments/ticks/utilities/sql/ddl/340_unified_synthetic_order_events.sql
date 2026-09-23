-- Every transition of every order the order engine runs, as an append-only log.
--
-- Written by bin/unified/orders/order_engine, which is the only process that sends an order to a broker when the REST
-- API is configured with UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT=engine. A parent order is one thing the caller
-- asked for - a plain limit order, a bracket, an OCO pair, a chaser - and a leg is one order the engine actually sends
-- to a broker on its behalf. A plain order is the degenerate case: one parent with one leg.
--
-- This table is the engine's record, and Redis is only its cache. On start the engine replays these rows through the
-- same state machine the live path uses and rebuilds every parent that has not finished, so a restart during market
-- hours does not abandon a position with a stop resting at a broker.
--
-- The write order is what makes that work. Before a leg's request leaves the machine the engine writes a leg_requested
-- row and commits it, so a crash mid-send still leaves evidence that an order may exist at the broker. `detail` on that
-- row carries the request as a dry run would show it, which is what lets the orphan matcher recognise the order in the
-- broker's own book afterwards.
--
-- `time` is when the engine recorded the transition. `sequence` counts transitions within one parent from 1, so the
-- order of two rows written in the same millisecond is never in doubt. `event` names what happened: parent_received,
-- parent_planned, leg_requested, leg_answered, leg_update, leg_filled, leg_cancel_requested, leg_cancelled,
-- parent_state_changed, parent_finished, orphan_suspected, orphan_attributed or orphan_abandoned.
--
-- `tag_sent` and `identifier_sent` record what actually went to the broker rather than what was asked for. The caller's
-- own tag is sent unchanged on the leg the caller asked for; a leg the engine invents, such as a stop or a target,
-- carries the parent's own short tag instead, because it has no caller tag to preserve.
--
-- The unified schema is created by the mapping DDL; the line below only makes this file safe to apply on its own.

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.synthetic_order_events (
    "time"              TIMESTAMPTZ    NOT NULL,
    parent_order_id     UUID           NOT NULL,
    sequence            BIGINT         NOT NULL,
    event               TEXT           NOT NULL,
    synthetic_type      TEXT,
    parent_state        TEXT,
    leg_id              TEXT,
    leg_role            TEXT,
    leg_state           TEXT,
    broker              TEXT,
    broker_order_id     TEXT,
    exchange_order_id   TEXT,
    tag_sent            TEXT,
    identifier_sent     TEXT,
    intent_id           UUID,
    instrument_id       UUID,
    transaction_type    TEXT,
    product             TEXT,
    order_type          TEXT,
    validity            TEXT,
    quantity            BIGINT,
    filled_quantity     BIGINT,
    price               NUMERIC(18,4),
    trigger_price       NUMERIC(18,4),
    average_price       NUMERIC(18,4),
    outcome             TEXT,
    status_message      TEXT,
    engine_instance     TEXT,
    detail              JSONB
    -- No primary key, for two reasons. A hypertable's unique index has to include the partitioning column, so
    -- UNIQUE (parent_order_id, sequence) is not available and adding "time" to it would not give the guarantee
    -- anyway. And a row written twice is harmless here: recovery folds events by (parent_order_id, sequence) and
    -- keeps the first, so a duplicate is ignored rather than turning into a failed insert on the order path.
);

-- One parent's whole life is the query that matters, and a parent lives for minutes to hours, so a day to a chunk
-- keeps a recovery scan inside one or two chunks while leaving them large enough to be worth compressing.
SELECT create_hypertable(
    'unified.synthetic_order_events',
    by_range('time', INTERVAL '1 day'),
    if_not_exists => TRUE
);

-- Recovery reads every row of one parent in order.
CREATE INDEX IF NOT EXISTS synthetic_order_events_parent_sequence_idx
    ON unified.synthetic_order_events (parent_order_id, sequence);

-- The orphan matcher and any later investigation start from a broker's own order id.
CREATE INDEX IF NOT EXISTS synthetic_order_events_broker_order_idx
    ON unified.synthetic_order_events (broker, broker_order_id, "time" DESC);

-- The recovery scan itself is a time range over every parent.
CREATE INDEX IF NOT EXISTS synthetic_order_events_time_idx
    ON unified.synthetic_order_events ("time" DESC);

ALTER TABLE unified.synthetic_order_events SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'parent_order_id',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'unified.synthetic_order_events',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);
