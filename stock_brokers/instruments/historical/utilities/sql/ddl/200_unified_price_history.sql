-- Historical prices for every unified instrument, one table across all brokers, which `bin/unified/historical_prices`
-- builds. Its sources, factors and corrections (210-250) follow it, resolving against `unified.instruments`, which the
-- mapping DDL creates.
--
-- Depends on the mapping DDL having run first: the unified schema and unified.instruments are
-- created by stock_brokers/instruments/mapping/utilities/sql/ddl (100-120). The schema line below is there so
-- this file is safe to apply on its own, not as a substitute for that order.
--
-- Prices are stored UNADJUSTED for the securities that split - equities, exchange traded funds and
-- investment trusts - and exactly as the broker served them for everything else. Adjustment is
-- applied on read, from unified.adjustment_factors, through unified.price_history_adjusted
-- and unified.adjusted_bars. Brokers that serve adjusted history disagree on the factors, apply
-- them at different times, and our stored copies never pick up an adjustment published after the
-- download, so storing their adjusted prices would store a mix of all of that.
--
-- The same shape as the per-broker price tables, with the unified instrument id in place of the
-- broker's token, and source_id naming where each bar came from.

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.price_history (
    "time"         TIMESTAMPTZ   NOT NULL,
    instrument_id  UUID          NOT NULL,
    "interval"     TEXT          NOT NULL,
    open           NUMERIC(18,4),
    high           NUMERIC(18,4),
    low            NUMERIC(18,4),
    close          NUMERIC(18,4),
    volume         BIGINT,
    oi             BIGINT,
    -- unified.price_history_sources. Not a foreign key: a reference checked on every row of a
    -- hypertable load is a cost paid millions of times for a guarantee the loader already gives.
    source_id      INTEGER       NOT NULL,
    loaded_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, "interval", "time")
);

-- One month chunks, for the same reason as the broker tables: daily bars back two decades would
-- otherwise spread across chunks too small to be worth their overhead.
SELECT create_hypertable(
    'unified.price_history',
    by_range('time', INTERVAL '1 month'),
    if_not_exists => TRUE
);

-- Compressed by instrument and interval, which is how the table is read.
ALTER TABLE unified.price_history SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'instrument_id, "interval"',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'unified.price_history',
    after => INTERVAL '30 days',
    if_not_exists => TRUE
);
