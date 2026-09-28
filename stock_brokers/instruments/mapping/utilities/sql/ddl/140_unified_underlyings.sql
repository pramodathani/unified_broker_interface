CREATE TABLE IF NOT EXISTS unified.underlyings (
    "instrument_id" UUID NOT NULL,
    "mapping_date" DATE NOT NULL,
    "segment" TEXT NOT NULL,
    "underlying_instrument_id" UUID,
    "status" TEXT NOT NULL,
    "sources" JSONB NOT NULL,
    PRIMARY KEY ("instrument_id", "mapping_date")
);

CREATE INDEX IF NOT EXISTS underlyings_date_segment_idx
    ON unified.underlyings ("mapping_date", "segment", "status");

SELECT create_hypertable(
    'unified.underlyings',
    by_range('mapping_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
