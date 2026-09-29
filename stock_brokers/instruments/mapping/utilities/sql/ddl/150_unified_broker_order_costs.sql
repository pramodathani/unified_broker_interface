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
