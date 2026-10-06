CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.order_execution_costs (
    "time"                      TIMESTAMPTZ    NOT NULL,
    parent_order_id             UUID           NOT NULL,
    leg_id                      TEXT           NOT NULL,
    synthetic_type              TEXT,
    leg_role                    TEXT,
    broker                      TEXT,
    instrument_id               UUID           NOT NULL,
    segment                     TEXT,
    transaction_type            TEXT           NOT NULL,
    product                     TEXT,
    order_type                  TEXT,
    quantity                    BIGINT,
    filled_quantity             BIGINT         NOT NULL,
    average_price               NUMERIC(18,4)  NOT NULL,
    decided_at                  TIMESTAMPTZ    NOT NULL,
    answered_at                 TIMESTAMPTZ,
    decision_quote_time         TIMESTAMPTZ,
    send_quote_time             TIMESTAMPTZ,
    answer_quote_time           TIMESTAMPTZ,
    decision_mid                NUMERIC(18,4),
    send_mid                    NUMERIC(18,4),
    answer_mid                  NUMERIC(18,4),
    delay_cost                  NUMERIC(18,4),
    latency_cost                NUMERIC(18,4),
    half_spread_cost            NUMERIC(18,4),
    beyond_touch_cost           NUMERIC(18,4),
    total_cost                  NUMERIC(18,4),
    total_cost_basis_points     NUMERIC(12,2),
    latency_cost_basis_points   NUMERIC(12,2),
    total_cost_rupees           NUMERIC(18,2),
    measured_at                 TIMESTAMPTZ    NOT NULL DEFAULT now()
);

SELECT create_hypertable(
    'unified.order_execution_costs',
    by_range('time', INTERVAL '7 days'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS order_execution_costs_broker_time_idx
    ON unified.order_execution_costs (broker, "time" DESC);

CREATE INDEX IF NOT EXISTS order_execution_costs_parent_idx
    ON unified.order_execution_costs (parent_order_id, leg_id);
