CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.daily_orders (
    trading_day                 DATE           NOT NULL,
    broker                      TEXT           NOT NULL,
    order_id                    TEXT           NOT NULL,
    exchange_order_id           TEXT,
    engine_parent_id            UUID,
    leg_role                    TEXT,
    status                      TEXT,
    status_message              TEXT,
    instrument_id               UUID,
    tradingsymbol               TEXT,
    exchange                    TEXT,
    transaction_type            TEXT,
    product                     TEXT,
    order_type                  TEXT,
    quantity                    BIGINT,
    filled_quantity             BIGINT,
    price                       NUMERIC(18,4),
    trigger_price               NUMERIC(18,4),
    average_price               NUMERIC(18,4),
    order_timestamp             TIMESTAMPTZ,
    exchange_timestamp          TIMESTAMPTZ,
    "order"                     JSONB          NOT NULL,
    stored_at                   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (trading_day, broker, order_id)
);

CREATE INDEX IF NOT EXISTS daily_orders_engine_parent_idx
    ON unified.daily_orders (engine_parent_id);
