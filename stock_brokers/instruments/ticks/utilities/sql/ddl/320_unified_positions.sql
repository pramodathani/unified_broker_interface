-- Every position snapshot a broker's websocket delivered, one table across all brokers.
--
-- Written by bin/unified/portfolio/store_positions_to_db from the unified position update stream bin/unified/orders/websocket_order_details fills,
-- for the brokers that stream positions (fyers, groww, kotak, wisdom_capital). Each row is one position at one broker at
-- one moment, in the REST API's position contract as bin/unified/portfolio/positions emits a single broker's position: resolved to
-- its unified.instruments id where the unified cache names one, product on the API's words (delivery, intraday, carry,
-- margin_trading, cover, bracket), quantity signed, buy and sell each as quantity, average price and value, and profit
-- as the broker reported it. A position is a snapshot rather than an event, so the history is the series of rows.
--
-- `time` is when the broker's own script received the update. `position_key` is the field the broker's script keys the
-- position by in its merged positions hash, and `basis` is `net` or, for a Wisdom Capital day-wise position, `day`.
-- Position update streams carry no prices, so `last_price` and the day change are usually NULL.
--
-- The unified schema is created by the mapping DDL; the line below only makes this file safe to apply on its own.

CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.positions (
    "time"                  TIMESTAMPTZ    NOT NULL,
    broker                  TEXT           NOT NULL,
    position_key            TEXT           NOT NULL,
    basis                   TEXT,
    instrument_id           UUID,
    symbol                  TEXT,
    exchange                TEXT,
    segment                 TEXT,
    expiry_date             DATE,
    strike_price            NUMERIC(18,4),
    option_type             TEXT,
    product                 TEXT,
    quantity                NUMERIC(20,4),
    buy_quantity            NUMERIC(20,4),
    buy_average_price       NUMERIC(18,4),
    buy_value               NUMERIC(24,4),
    sell_quantity           NUMERIC(20,4),
    sell_average_price      NUMERIC(18,4),
    sell_value              NUMERIC(24,4),
    average_price           NUMERIC(18,4),
    last_price              NUMERIC(18,4),
    realized_pnl            NUMERIC(24,4),
    unrealized_pnl          NUMERIC(24,4),
    total_pnl               NUMERIC(24,4),
    day_change              NUMERIC(18,4),
    day_change_percentage   NUMERIC(12,4)
    -- No primary key, for the same reason as unified.order_updates.
);

-- Sparse beside ticks, so a month to a chunk.
SELECT create_hypertable(
    'unified.positions',
    by_range('time', INTERVAL '1 month'),
    if_not_exists => TRUE
);

-- The query that matters: one position's snapshots at one broker, most recent first.
CREATE INDEX IF NOT EXISTS positions_broker_key_time_idx
    ON unified.positions (broker, position_key, "time" DESC);

CREATE INDEX IF NOT EXISTS positions_instrument_time_idx
    ON unified.positions (instrument_id, "time" DESC);

ALTER TABLE unified.positions SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'broker, position_key',
    timescaledb.orderby = '"time" DESC'
);

CALL add_columnstore_policy(
    'unified.positions',
    after => INTERVAL '7 days',
    if_not_exists => TRUE
);
