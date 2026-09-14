CREATE TABLE IF NOT EXISTS groww.instruments (
    "exchange" TEXT,
    "exchange_token" TEXT,
    "trading_symbol" TEXT,
    "groww_symbol" TEXT,
    "name" TEXT,
    "instrument_type" TEXT,
    "segment" TEXT,
    "series" TEXT,
    "isin" TEXT,
    "underlying_symbol" TEXT,
    "underlying_exchange_token" TEXT,
    "expiry_date" TEXT,
    "strike_price" TEXT,
    "lot_size" TEXT,
    "tick_size" TEXT,
    "freeze_quantity" TEXT,
    "is_reserved" TEXT,
    "buy_allowed" TEXT,
    "sell_allowed" TEXT,
    "internal_trading_symbol" TEXT,
    "is_intraday" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'groww.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
