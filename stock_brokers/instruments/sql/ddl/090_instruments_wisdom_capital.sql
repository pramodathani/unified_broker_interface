CREATE TABLE IF NOT EXISTS wisdom_capital.instruments (
    "exchangesegment" TEXT,
    "exchangeinstrumentid" TEXT,
    "instrumenttype" TEXT,
    "name" TEXT,
    "description" TEXT,
    "series" TEXT,
    "namewithseries" TEXT,
    "instrumentid" TEXT,
    "priceband_high" TEXT,
    "priceband_low" TEXT,
    "freezeqty" TEXT,
    "ticksize" TEXT,
    "lotsize" TEXT,
    "multiplier" TEXT,
    "displayname" TEXT,
    "isin" TEXT,
    "pricenumerator" TEXT,
    "pricedenominator" TEXT,
    "detaileddescription" TEXT,
    "extendedsurvindicator" TEXT,
    "cautionindicator" TEXT,
    "gsmindicator" TEXT,
    "data_category" TEXT,
    "underlyinginstrumentid" TEXT,
    "underlyingindexname" TEXT,
    "contractexpiration" TEXT,
    "strikeprice" TEXT,
    "optiontype" TEXT,
    "download_date" DATE NOT NULL
);

SELECT create_hypertable(
    'wisdom_capital.instruments',
    by_range('download_date', INTERVAL '1 month'),
    if_not_exists => TRUE
);
