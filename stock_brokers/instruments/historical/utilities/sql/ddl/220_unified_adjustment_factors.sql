-- Split, bonus and demerger factors for the securities stored unadjusted.
--
-- One row per instrument, ex-date and kind. `price_factor` multiplies the prices of every bar before
-- `ex_date`; `volume_factor` multiplies their volume. For a 5-for-1 split both come from the exact
-- ratio (0.2 and 5). For a demerger only prices move, by a factor discovered from prices rather
-- than declared (RELIANCE and Jio Financial, 2023-07-20, about 0.923), so volume_factor is 1.
-- Dividends are deliberately not here.
--
-- Factors come from Yahoo Finance: its listed split events, confirmed against our own raw prices,
-- and factors derived from how Yahoo's Close moves relative to our raw close, which is how demergers
-- Yahoo never lists as events are found. Only `confirmed` factors are applied on read. `provisional`
-- ones wait for a person. `rejected` ones are kept rather than deleted, so that a rebuild cannot
-- quietly resurrect an event that was looked at and found not to exist - INDIAGLYCO's 2.0 split
-- on 2025-08-12, which moved neither Yahoo's own prices nor ours. The builder never overwrites a
-- row whose source is 'manual'.

CREATE TABLE IF NOT EXISTS unified.adjustment_factors (
    instrument_id        UUID        NOT NULL REFERENCES unified.instruments (instrument_id),
    ex_date              DATE        NOT NULL,
    kind                 TEXT        NOT NULL
        CHECK (kind IN ('split', 'bonus', 'demerger', 'unclassified')),
    -- The exact ratio when one is known: a 5-for-1 split is 5 and 1, a 1:1 bonus 2 and 1.
    shares_after         NUMERIC,
    shares_before        NUMERIC,
    price_factor         NUMERIC     NOT NULL CHECK (price_factor > 0),
    volume_factor        NUMERIC     NOT NULL CHECK (volume_factor > 0),
    status               TEXT        NOT NULL CHECK (status IN ('confirmed', 'provisional', 'rejected')),
    source               TEXT        NOT NULL
        CHECK (source IN ('yahoo_split_event', 'yahoo_close_ratio', 'raw_gap', 'manual')),
    yahoo_symbol         TEXT,
    yahoo_event_date     DATE,
    yahoo_event_ratio    NUMERIC,
    -- The step measured in Yahoo's Close relative to our raw close, and how noisy the measurement was.
    observed_step        NUMERIC,
    observed_dispersion  NUMERIC,
    evidence             JSONB,
    first_detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, ex_date, kind)
);

CREATE INDEX IF NOT EXISTS adjustment_factors_status_idx
    ON unified.adjustment_factors (status, ex_date DESC);
