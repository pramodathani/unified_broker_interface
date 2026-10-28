CREATE SCHEMA IF NOT EXISTS unified;

CREATE TABLE IF NOT EXISTS unified.stop_slippage (
    fired_at                    TIMESTAMPTZ    NOT NULL,
    parent_order_id             UUID           NOT NULL,
    instrument_id               UUID           NOT NULL,
    segment                     TEXT,
    transaction_type            TEXT           NOT NULL,
    trigger_field               TEXT,
    trigger_price               NUMERIC(18,4)  NOT NULL,
    closed_by                   TEXT,
    filled_quantity             BIGINT,
    average_price               NUMERIC(18,4),
    slip                        NUMERIC(18,4),
    slip_basis_points           NUMERIC(12,2),
    measured_at                 TIMESTAMPTZ    NOT NULL DEFAULT now()
);

SELECT create_hypertable(
    'unified.stop_slippage',
    by_range('fired_at', INTERVAL '7 days'),
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS stop_slippage_segment_time_idx
    ON unified.stop_slippage (segment, transaction_type, fired_at DESC);
