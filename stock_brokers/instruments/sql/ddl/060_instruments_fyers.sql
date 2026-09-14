CREATE TABLE IF NOT EXISTS fyers.instruments (
    "fytoken" TEXT,
    "symbol_details" TEXT,
    "exchange_instrument_type" TEXT,
    "minimum_lot_size" TEXT,
    "tick_size" TEXT,
    "isin" TEXT,
    "trading_session" TEXT,
    "last_update_date" TEXT,
    "expiry_date" TEXT,
    "symbol_ticker" TEXT,
    "exchange" TEXT,
    "segment" TEXT,
    "scrip_code" TEXT,
    "underlying_symbol" TEXT,
    "underlying_scrip_code" TEXT,
    "strike_price" TEXT,
    "option_type" TEXT,
    "underlying_fytoken" TEXT,
    "reserved_column1" TEXT,
    "reserved_column2" TEXT,
    "reserved_column3" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'fyers.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
