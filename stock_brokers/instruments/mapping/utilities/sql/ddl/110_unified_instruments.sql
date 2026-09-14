-- One row per real-world instrument, converged from every broker that carries it.
--
-- `instrument_id` is not allocated, it is computed: a UUID5 over (exchange, segment, shape, the identity fields for
-- that shape). Two brokers publishing the same contract arrive at the same id independently, which is what lets the
-- upsert merge them with no matching step and no registry. The three partial unique indexes state that identity per
-- shape, so a second row claiming the same real instrument is rejected by the database rather than merely unlikely.
--
-- `first_seen_date` and `last_seen_date` only ever widen, through LEAST and GREATEST in the upsert.

CREATE TABLE IF NOT EXISTS unified.instruments (
    "instrument_id" UUID NOT NULL,
    "exchange" TEXT NOT NULL,
    "segment" TEXT NOT NULL,
    "shape" TEXT NOT NULL,
    "symbol" TEXT,
    "underlying_symbol" TEXT,
    "expiry_date" DATE,
    "strike_price" NUMERIC,
    "option_type" TEXT,
    "first_seen_date" DATE NOT NULL,
    "last_seen_date" DATE NOT NULL,
    PRIMARY KEY ("instrument_id")
);

CREATE UNIQUE INDEX IF NOT EXISTS instruments_security_uk
    ON unified.instruments ("exchange", "segment", "symbol") WHERE "shape" = 'security';

CREATE UNIQUE INDEX IF NOT EXISTS instruments_future_uk
    ON unified.instruments ("exchange", "segment", "underlying_symbol", "expiry_date") WHERE "shape" = 'future';

CREATE UNIQUE INDEX IF NOT EXISTS instruments_option_uk
    ON unified.instruments ("exchange", "segment", "underlying_symbol", "expiry_date", "strike_price", "option_type")
    WHERE "shape" = 'option';

CREATE INDEX IF NOT EXISTS instruments_segment_idx ON unified.instruments ("segment", "exchange");
