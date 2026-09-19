CREATE TABLE IF NOT EXISTS indmoney.instruments (
    "exch" TEXT,
    "segment" TEXT,
    "security_id" TEXT,
    "instrument_name" TEXT,
    "expiry_code" TEXT,
    "trading_symbol" TEXT,
    "lot_units" TEXT,
    "custom_symbol" TEXT,
    "expiry_date" TEXT,
    "strike_price" TEXT,
    "option_type" TEXT,
    "tick_size" TEXT,
    "expiry_flag" TEXT,
    "sem_exch_instrument_type" TEXT,
    "series" TEXT,
    "symbol_name" TEXT,
    "underlying_scrip_name" TEXT,
    "freeze_qty" TEXT,
    "upper_limit" TEXT,
    "lower_limit" TEXT,
    "isin" TEXT,
    "general_factor" TEXT,
    "delivery_unit" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'indmoney.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);

ALTER TABLE indmoney.instruments ADD COLUMN IF NOT EXISTS "intraday_leverage" TEXT;
ALTER TABLE indmoney.instruments ADD COLUMN IF NOT EXISTS "haircut_percentage" TEXT;
ALTER TABLE indmoney.instruments ADD COLUMN IF NOT EXISTS "pledge_eligible" TEXT;
