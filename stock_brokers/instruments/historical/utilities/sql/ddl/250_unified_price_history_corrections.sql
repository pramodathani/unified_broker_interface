-- Multipliers that undo an adjustment a broker had already applied to a series it served.
--
-- unified.price_history stores equities, exchange traded funds and investment trusts raw. flattrade
-- is the source for those, and its BSE daily bars are raw, but its NSE daily bars are raw across some
-- corporate actions and already adjusted across others: before PIDILITIND's 1:1 bonus of 2025-09-23
-- its NSE close is exactly half the BSE close, and half its own last 15 minute bar of the same day.
-- A row here says that one broker series, at one interval, was served with every price before
-- `ex_date` divided by `price_multiplier`, so the loader multiplies them back.
--
-- Only prices are affected: flattrade left volume as traded (PIDILITIND's NSE daily volume more than
-- doubles across its bonus), so `volume_multiplier` is 1 unless a case shows otherwise.
--
-- `method` says how the pre-adjustment was found:
--   cross_exchange  the ratio of the other exchange's close to this one stepped at ex_date, and this
--                   series' own close did not move there while the other's did
--   intraday        the ratio of the broker's own raw last intraday bar to this daily close stepped
--   yahoo_event     Yahoo lists a split there and the series shows no step; indistinguishable from a
--                   phantom event on its own, so never confirmed automatically
--   manual          set by a person
--
-- Only `confirmed` rows are applied. As with adjustment factors, `manual` rows are never overwritten
-- and `rejected` rows are never revived by a rebuild.

CREATE TABLE IF NOT EXISTS unified.price_history_corrections (
    broker             TEXT        NOT NULL,
    broker_series      TEXT        NOT NULL,
    "interval"         TEXT        NOT NULL,
    ex_date            DATE        NOT NULL,
    instrument_id      UUID        NOT NULL REFERENCES unified.instruments (instrument_id),
    price_multiplier   NUMERIC     NOT NULL CHECK (price_multiplier > 0),
    volume_multiplier  NUMERIC     NOT NULL DEFAULT 1 CHECK (volume_multiplier > 0),
    method             TEXT        NOT NULL CHECK (method IN ('cross_exchange', 'intraday', 'yahoo_event', 'manual')),
    status             TEXT        NOT NULL CHECK (status IN ('confirmed', 'provisional', 'rejected')),
    -- The simple ratio the observation was snapped to, as "2/1", or NULL when it was not simple.
    snapped_ratio      TEXT,
    observed           NUMERIC,
    evidence           JSONB,
    first_detected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (broker, broker_series, "interval", ex_date)
);

CREATE INDEX IF NOT EXISTS price_history_corrections_instrument_idx
    ON unified.price_history_corrections (instrument_id, "interval");

-- The combined multiplier applying to each span of a series between consecutive confirmed ex-dates,
-- the same shape as unified.adjustment_ranges. Bars after the last ex-date have no row.
CREATE OR REPLACE VIEW unified.correction_ranges AS
WITH per_ex_date AS (
    SELECT broker, broker_series, "interval", ex_date,
           sum(ln(price_multiplier))  AS log_price,
           sum(ln(volume_multiplier)) AS log_volume
    FROM unified.price_history_corrections
    WHERE status = 'confirmed'
    GROUP BY broker, broker_series, "interval", ex_date
),
cumulative AS (
    SELECT broker, broker_series, "interval", ex_date,
           lag(ex_date) OVER (PARTITION BY broker, broker_series, "interval" ORDER BY ex_date) AS previous_ex_date,
           sum(log_price) OVER later  AS log_price,
           sum(log_volume) OVER later AS log_volume
    FROM per_ex_date
    WINDOW later AS (PARTITION BY broker, broker_series, "interval" ORDER BY ex_date DESC
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT broker, broker_series, "interval", previous_ex_date, ex_date,
       CASE WHEN previous_ex_date IS NULL THEN '-infinity'::timestamptz
            ELSE previous_ex_date::timestamp AT TIME ZONE 'Asia/Kolkata' END AS valid_from,
       ex_date::timestamp AT TIME ZONE 'Asia/Kolkata'                        AS valid_to,
       round(exp(log_price), 12)                                             AS price_multiplier,
       round(exp(log_volume), 12)                                            AS volume_multiplier
FROM cumulative;
