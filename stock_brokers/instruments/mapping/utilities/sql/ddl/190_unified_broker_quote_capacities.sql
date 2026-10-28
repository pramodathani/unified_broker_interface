CREATE TABLE IF NOT EXISTS unified.broker_quote_capacities (
    "broker" TEXT PRIMARY KEY,
    "sockets" INTEGER NOT NULL CHECK ("sockets" >= 0),
    "instruments_per_socket" INTEGER NOT NULL CHECK ("instruments_per_socket" >= 0),
    "measured_on" DATE,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO unified.broker_quote_capacities (
    "broker",
    "sockets",
    "instruments_per_socket",
    "measured_on"
)
VALUES
    ('dhan', 10, 5000, DATE '2026-10-27'),
    ('flattrade', 0, 0, NULL),
    ('fyers', 1, 100, DATE '2026-10-27'),
    ('groww', 0, 0, NULL),
    ('indmoney', 1, 3000, DATE '2026-10-27'),
    ('kotak', 45, 3000, DATE '2026-10-28'),
    ('shoonya', 1, 100, DATE '2026-10-27'),
    ('stoxkart', 4, 50000, DATE '2026-10-27'),
    ('wisdom_capital', 1, 50, DATE '2026-10-27'),
    ('zerodha', 24, 4000, DATE '2026-10-27')
ON CONFLICT ("broker") DO NOTHING;

ALTER TABLE unified.broker_quote_capacities ADD COLUMN IF NOT EXISTS "preference" INTEGER NOT NULL DEFAULT 100;

UPDATE unified.broker_quote_capacities
SET "preference" = seed."preference"
FROM (
    VALUES
        ('zerodha', 1),
        ('fyers', 2),
        ('dhan', 3),
        ('indmoney', 6),
        ('shoonya', 4),
        ('flattrade', 4),
        ('wisdom_capital', 4),
        ('kotak', 2),
        ('stoxkart', 5)
) AS seed ("broker", "preference")
WHERE unified.broker_quote_capacities."broker" = seed."broker"
  AND unified.broker_quote_capacities."preference" = 100;
