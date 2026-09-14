-- Which token each broker uses for each instrument, on each day.
--
-- Dated rather than current, because a broker can renumber a scrip: a position opened in March has to be read back with
-- March's token, not today's. `broker_token` is also the join key back into that broker's own raw snapshot in
-- `<broker>.instruments`, so any column the mapping does not carry is one lookup away. A token is not unique within a
-- broker and date - Dhan reuses a security id across segments - so the key is the instrument, the broker and the date.

CREATE TABLE IF NOT EXISTS unified.broker_mappings (
    "instrument_id" UUID NOT NULL,
    "broker" TEXT NOT NULL,
    "broker_token" TEXT NOT NULL,
    "broker_symbol" TEXT,
    "order_symbol" TEXT,
    "lot_size" NUMERIC,
    "tick_size" NUMERIC,
    "mapping_date" DATE NOT NULL,
    PRIMARY KEY ("instrument_id", "broker", "mapping_date"),
    FOREIGN KEY ("instrument_id") REFERENCES unified.instruments ("instrument_id")
);

CREATE INDEX IF NOT EXISTS broker_mappings_token_idx
    ON unified.broker_mappings ("broker", "broker_token", "mapping_date");

CREATE INDEX IF NOT EXISTS broker_mappings_date_idx
    ON unified.broker_mappings ("mapping_date", "instrument_id");

SELECT create_hypertable(
    'unified.broker_mappings',
    by_range('mapping_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
