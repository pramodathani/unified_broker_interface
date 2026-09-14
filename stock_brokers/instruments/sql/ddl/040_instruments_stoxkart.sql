CREATE TABLE IF NOT EXISTS stoxkart.instruments (
    "exchange" TEXT,
    "market_segment_id" TEXT,
    "token" TEXT,
    "symbol" TEXT,
    "symbol_description" TEXT,
    "series" TEXT,
    "instrument_type" TEXT,
    "option_type" TEXT,
    "expiry_date" TEXT,
    "lot_size" TEXT,
    "strike_price" TEXT,
    "isin_code" TEXT,
    "tick_size" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'stoxkart.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
