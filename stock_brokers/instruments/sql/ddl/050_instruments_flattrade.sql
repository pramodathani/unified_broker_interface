CREATE TABLE IF NOT EXISTS flattrade.instruments (
    "exchange" TEXT,
    "token" TEXT,
    "lotsize" TEXT,
    "symbol" TEXT,
    "tradingsymbol" TEXT,
    "instrument" TEXT,
    "expiry" TEXT,
    "strike" TEXT,
    "optiontype" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'flattrade.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
