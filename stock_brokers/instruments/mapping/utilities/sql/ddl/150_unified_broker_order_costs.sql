CREATE TABLE IF NOT EXISTS unified.broker_order_costs (
    "broker" TEXT PRIMARY KEY,
    "orders_per_sec" INTEGER CHECK ("orders_per_sec" > 0),
    "orders_per_minute" INTEGER CHECK ("orders_per_minute" > 0),
    "orders_per_hour" INTEGER CHECK ("orders_per_hour" > 0),
    "orders_per_day" INTEGER CHECK ("orders_per_day" > 0),
    "brokerage_for_delivery" NUMERIC NOT NULL CHECK ("brokerage_for_delivery" >= 0),
    "brokerage_for_fno" NUMERIC NOT NULL CHECK ("brokerage_for_fno" >= 0),
    "brokerage_for_intraday" NUMERIC NOT NULL CHECK ("brokerage_for_intraday" >= 0),
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO unified.broker_order_costs (
    "broker",
    "orders_per_sec",
    "orders_per_minute",
    "orders_per_hour",
    "orders_per_day",
    "brokerage_for_delivery",
    "brokerage_for_fno",
    "brokerage_for_intraday"
)
VALUES
    ('dhan', 9, 480, 7000, NULL, 0, 20, 20),
    ('flattrade', 10, 180, NULL, NULL, 0, 0, 0),
    ('fyers', 8, 180, NULL, 100000, 0, 20, 20),
    ('groww', 9, 240, NULL, NULL, 20, 20, 20),
    ('indmoney', 7, 540, NULL, NULL, 20, 20, 20),
    ('kotak', 9, 600, NULL, NULL, 20, 20, 10),
    ('shoonya', 8, 540, NULL, NULL, 0, 5, 5),
    ('stoxkart', 6, 420, NULL, NULL, 0, 20, 20),
    ('wisdom_capital', 8, 540, NULL, NULL, 0, 0, 0),
    ('zerodha', 9, 375, NULL, 4500, 0, 20, 20)
ON CONFLICT ("broker") DO NOTHING;

ALTER TABLE unified.broker_order_costs ADD COLUMN IF NOT EXISTS "margin_multiplier_intraday" NUMERIC CHECK ("margin_multiplier_intraday" >= 1);
ALTER TABLE unified.broker_order_costs ADD COLUMN IF NOT EXISTS "margin_multiplier_fno" NUMERIC CHECK ("margin_multiplier_fno" >= 1);
ALTER TABLE unified.broker_order_costs ADD COLUMN IF NOT EXISTS "margin_multiplier_commodity" NUMERIC CHECK ("margin_multiplier_commodity" >= 1);
ALTER TABLE unified.broker_order_costs ADD COLUMN IF NOT EXISTS "gives_hedge_benefit" BOOLEAN;
ALTER TABLE unified.broker_order_costs ADD COLUMN IF NOT EXISTS "margin_calibrated_at" TIMESTAMPTZ;

UPDATE unified.broker_order_costs AS costs
SET
    "margin_multiplier_intraday" = COALESCE(costs."margin_multiplier_intraday", seed."intraday"),
    "margin_multiplier_fno" = COALESCE(costs."margin_multiplier_fno", seed."fno"),
    "margin_multiplier_commodity" = COALESCE(costs."margin_multiplier_commodity", seed."commodity"),
    "gives_hedge_benefit" = COALESCE(costs."gives_hedge_benefit", seed."hedge")
FROM (
    VALUES
        ('dhan', 1.000, 1.000, 1.000, TRUE),
        ('flattrade', 1.101, 1.111, 1.110, TRUE),
        ('fyers', 1.005, 1.001, 1.000, FALSE),
        ('groww', 1.000, 1.000, 1.000, TRUE),
        ('indmoney', 1.013, 1.005, NULL, NULL),
        ('kotak', 1.000, 1.000, 1.000, NULL),
        ('shoonya', 1.053, 1.055, 1.050, TRUE),
        ('stoxkart', NULL, NULL, NULL, NULL),
        ('wisdom_capital', 1.375, 1.100, NULL, TRUE),
        ('zerodha', 1.000, 1.000, 1.000, TRUE)
) AS seed ("broker", "intraday", "fno", "commodity", "hedge")
WHERE costs."broker" = seed."broker"
    AND costs."margin_calibrated_at" IS NULL
    AND (
        costs."margin_multiplier_intraday" IS NULL
        OR costs."margin_multiplier_fno" IS NULL
        OR costs."margin_multiplier_commodity" IS NULL
        OR costs."gives_hedge_benefit" IS NULL
    );
