CREATE TABLE IF NOT EXISTS unified.charge_rates (
    "segment" TEXT NOT NULL,
    "category" TEXT NOT NULL CHECK ("category" IN ('delivery', 'intraday', 'fno')),
    "stt_buy_rate" NUMERIC NOT NULL CHECK ("stt_buy_rate" >= 0 AND "stt_buy_rate" < 1),
    "stt_sell_rate" NUMERIC NOT NULL CHECK ("stt_sell_rate" >= 0 AND "stt_sell_rate" < 1),
    "exchange_rate" NUMERIC NOT NULL CHECK ("exchange_rate" >= 0 AND "exchange_rate" < 1),
    "sebi_rate" NUMERIC NOT NULL CHECK ("sebi_rate" >= 0 AND "sebi_rate" < 1),
    "stamp_buy_rate" NUMERIC NOT NULL CHECK ("stamp_buy_rate" >= 0 AND "stamp_buy_rate" < 1),
    "gst_rate" NUMERIC NOT NULL CHECK ("gst_rate" >= 0 AND "gst_rate" < 1),
    "checked_on" DATE,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("segment", "category")
);

INSERT INTO unified.charge_rates (
    "segment",
    "category",
    "stt_buy_rate",
    "stt_sell_rate",
    "exchange_rate",
    "sebi_rate",
    "stamp_buy_rate",
    "gst_rate",
    "checked_on"
)
VALUES
    ('nse_equity_index_options', 'fno', 0, 0.0015, 0.0003553, 0.000001, 0.00003, 0.18, '2026-10-19'),
    ('nse_equity_options', 'fno', 0, 0.0015, 0.0003553, 0.000001, 0.00003, 0.18, NULL),
    ('nse_equity_index_futures', 'fno', 0, 0.0005, 0.0000183, 0.000001, 0.00002, 0.18, NULL),
    ('nse_equity_futures', 'fno', 0, 0.0005, 0.0000183, 0.000001, 0.00002, 0.18, NULL),
    ('nse_equities', 'delivery', 0.001, 0.001, 0.0000307, 0.000001, 0.00015, 0.18, NULL),
    ('nse_equities', 'intraday', 0, 0.00025, 0.0000307, 0.000001, 0.00003, 0.18, NULL),
    ('bse_equity_index_options', 'fno', 0, 0.0015, 0.000325, 0.000001, 0.00003, 0.18, NULL),
    ('bse_equity_options', 'fno', 0, 0.0015, 0.000325, 0.000001, 0.00003, 0.18, NULL),
    ('bse_equities', 'delivery', 0.001, 0.001, 0.0000375, 0.000001, 0.00015, 0.18, NULL),
    ('bse_equities', 'intraday', 0, 0.00025, 0.0000375, 0.000001, 0.00003, 0.18, NULL)
ON CONFLICT ("segment", "category") DO NOTHING;
