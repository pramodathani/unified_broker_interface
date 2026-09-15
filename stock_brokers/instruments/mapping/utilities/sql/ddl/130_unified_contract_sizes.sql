CREATE TABLE IF NOT EXISTS unified.contract_sizes (
    "instrument_id" UUID NOT NULL,
    "mapping_date" DATE NOT NULL,
    "segment" TEXT NOT NULL,
    "units_per_lot" NUMERIC,
    "status" TEXT NOT NULL,
    "tradeable" BOOLEAN NOT NULL,
    "sources" JSONB NOT NULL,
    PRIMARY KEY ("instrument_id", "mapping_date")
);

CREATE INDEX IF NOT EXISTS contract_sizes_date_segment_idx
    ON unified.contract_sizes ("mapping_date", "segment", "status");

SELECT create_hypertable(
    'unified.contract_sizes',
    by_range('mapping_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
