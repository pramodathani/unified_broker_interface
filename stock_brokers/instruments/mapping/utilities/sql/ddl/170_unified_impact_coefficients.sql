CREATE TABLE IF NOT EXISTS unified.impact_coefficients (
    "asset_class" TEXT NOT NULL,
    "coefficient" NUMERIC NOT NULL CHECK ("coefficient" > 0),
    "fitted_at" TIMESTAMPTZ,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("asset_class")
);

INSERT INTO unified.impact_coefficients (
    "asset_class",
    "coefficient"
)
VALUES
    ('securities', 1.0),
    ('currency', 1.0),
    ('commodity', 1.0)
ON CONFLICT ("asset_class") DO NOTHING;
