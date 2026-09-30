CREATE TABLE IF NOT EXISTS unified.margin_rates (
    "segment" TEXT NOT NULL,
    "underlying" TEXT NOT NULL DEFAULT '',
    "span_rate" NUMERIC NOT NULL CHECK ("span_rate" >= 0 AND "span_rate" <= 1),
    "exposure_rate" NUMERIC NOT NULL CHECK ("exposure_rate" >= 0 AND "exposure_rate" <= 1),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("segment", "underlying")
);

INSERT INTO unified.margin_rates (
    "segment",
    "underlying",
    "span_rate",
    "exposure_rate"
)
VALUES
    ('nse_equities', '', 0.20, 0),
    ('bse_equities', '', 0.20, 0),
    ('nse_exchange_traded_funds', '', 0.20, 0),
    ('bse_exchange_traded_funds', '', 0.20, 0),
    ('nse_equity_index_futures', '', 0.12, 0.03),
    ('nse_equity_index_options', '', 0.12, 0.03),
    ('bse_equity_index_futures', '', 0.12, 0.03),
    ('bse_equity_index_options', '', 0.12, 0.03),
    ('nse_equity_index_futures', 'NIFTY', 0.0926, 0.02),
    ('nse_equity_index_options', 'NIFTY', 0.0926, 0.02),
    ('nse_equity_futures', '', 0.35, 0.05),
    ('nse_equity_options', '', 0.35, 0.05),
    ('bse_equity_futures', '', 0.35, 0.05),
    ('bse_equity_options', '', 0.35, 0.05),
    ('mcx_commodity_futures', '', 0.45, 0.02),
    ('mcx_commodity_options', '', 0.45, 0.02),
    ('mcx_commodity_futures', 'CRUDEOIL', 0.302, 0.0125),
    ('mcx_commodity_options', 'CRUDEOIL', 0.302, 0.0125),
    ('nse_commodity_futures', '', 0.45, 0.02),
    ('nse_commodity_options', '', 0.45, 0.02),
    ('nse_currency_futures', '', 0.05, 0.02),
    ('nse_currency_options', '', 0.05, 0.02),
    ('bse_currency_futures', '', 0.05, 0.02),
    ('bse_currency_options', '', 0.05, 0.02)
ON CONFLICT ("segment", "underlying") DO NOTHING;
