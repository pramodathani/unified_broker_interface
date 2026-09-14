CREATE TABLE IF NOT EXISTS shoonya.instruments (
    "exchange" TEXT,
    "token" TEXT,
    "lotsize" TEXT,
    "symbol" TEXT,
    "tradingsymbol" TEXT,
    "instrument" TEXT,
    "ticksize" TEXT,
    "expiry" TEXT,
    "optiontype" TEXT,
    "strikeprice" TEXT,
    "precision" TEXT,
    "multiplier" TEXT,
    "gngd" TEXT,
    "source_zip_url" TEXT,
    "source_file_name" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'shoonya.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
