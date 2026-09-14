-- Reading unified.price_history adjusted for splits, bonuses and demergers.
--
-- The stored prices stay raw. Adjustment happens here, on read, from the confirmed rows of
-- unified.adjustment_factors, so correcting a factor corrects every query at once and nothing
-- has to be rewritten.
--
-- A bar is multiplied by every confirmed factor whose ex-date falls after the bar's trading day.
-- Factors are compared by India trading date: an ex-date of 2024-10-28 applies to every bar before
-- midnight India time on 2024-10-28, which covers daily bars (stamped at that midnight) and
-- intraday bars alike.
--
-- Rows with no factors - futures, options, indices, and the many equities that never split - pass
-- through unchanged, because the join is a LEFT JOIN and a missing range means a factor of 1.
--
-- Two factors on one ex-date (a split and a demerger on the same day) are multiplied together. The
-- product is taken as exp(sum(ln(factor))), since PostgreSQL has no product aggregate, and rounded to
-- twelve places so that 0.5 comes back as 0.5 and not as 0.4999999999999999.

-- One row per instrument and span between consecutive ex-dates, carrying the combined factor that
-- applies to bars inside it. Bars after the last ex-date have no row.
CREATE OR REPLACE VIEW unified.adjustment_ranges AS
WITH per_ex_date AS (
    SELECT instrument_id,
           ex_date,
           sum(ln(price_factor))  AS log_price_factor,
           sum(ln(volume_factor)) AS log_volume_factor
    FROM unified.adjustment_factors
    WHERE status = 'confirmed'
    GROUP BY instrument_id, ex_date
),
cumulative AS (
    SELECT instrument_id,
           ex_date,
           lag(ex_date) OVER (PARTITION BY instrument_id ORDER BY ex_date) AS previous_ex_date,
           sum(log_price_factor) OVER later  AS log_price_factor,
           sum(log_volume_factor) OVER later AS log_volume_factor
    FROM per_ex_date
    WINDOW later AS (PARTITION BY instrument_id ORDER BY ex_date DESC
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT instrument_id,
       previous_ex_date,
       ex_date,
       CASE WHEN previous_ex_date IS NULL THEN '-infinity'::timestamptz
            ELSE previous_ex_date::timestamp AT TIME ZONE 'Asia/Kolkata' END AS valid_from,
       ex_date::timestamp AT TIME ZONE 'Asia/Kolkata'                        AS valid_to,
       round(exp(log_price_factor), 12)                                      AS price_factor,
       round(exp(log_volume_factor), 12)                                     AS volume_factor
FROM cumulative;

-- Every bar, adjusted with everything known today.
CREATE OR REPLACE VIEW unified.price_history_adjusted AS
SELECT p."time",
       p.instrument_id,
       p."interval",
       round(p.open  * coalesce(r.price_factor, 1), 4)                AS open,
       round(p.high  * coalesce(r.price_factor, 1), 4)                AS high,
       round(p.low   * coalesce(r.price_factor, 1), 4)                AS low,
       round(p.close * coalesce(r.price_factor, 1), 4)                AS close,
       round(p.volume * coalesce(r.volume_factor, 1))::bigint         AS volume,
       p.oi,
       coalesce(r.price_factor, 1)                                    AS price_factor,
       p.source_id
FROM unified.price_history p
LEFT JOIN unified.adjustment_ranges r
       ON r.instrument_id = p.instrument_id
      AND p."time" >= r.valid_from
      AND p."time" <  r.valid_to;

-- One instrument's bars over a time range, adjusted as they would have been on `known_as_of`.
--
-- With known_as_of left NULL this is the view above for one series. With a date, only factors
-- whose ex-date is on or before that date are applied - which is what a chart on that day showed,
-- and what a backtest standing on that day may use. Without it, a backtest of 2023 would see prices
-- already halved for a bonus that went ex in 2024.
--
-- Written as a single SQL SELECT marked STABLE, so PostgreSQL inlines it into the calling query and
-- the instrument, interval and time conditions reach the hypertable's chunk exclusion.
CREATE OR REPLACE FUNCTION unified.adjusted_bars(
    p_instrument_id UUID,
    p_interval      TEXT,
    p_from          TIMESTAMPTZ,
    p_to            TIMESTAMPTZ,
    p_known_as_of   DATE DEFAULT NULL
)
RETURNS TABLE (
    "time"        TIMESTAMPTZ,
    open          NUMERIC,
    high          NUMERIC,
    low           NUMERIC,
    close         NUMERIC,
    volume        BIGINT,
    oi            BIGINT,
    price_factor  NUMERIC,
    source_id     INTEGER
)
LANGUAGE sql STABLE
AS $$
    WITH per_ex_date AS (
        SELECT ex_date,
               sum(ln(price_factor))  AS log_price_factor,
               sum(ln(volume_factor)) AS log_volume_factor
        FROM unified.adjustment_factors
        WHERE instrument_id = p_instrument_id
          AND status = 'confirmed'
          AND (p_known_as_of IS NULL OR ex_date <= p_known_as_of)
        GROUP BY ex_date
    ),
    ranges AS (
        SELECT CASE WHEN lag(ex_date) OVER (ORDER BY ex_date) IS NULL THEN '-infinity'::timestamptz
                    ELSE lag(ex_date) OVER (ORDER BY ex_date)::timestamp AT TIME ZONE 'Asia/Kolkata'
               END                                                               AS valid_from,
               ex_date::timestamp AT TIME ZONE 'Asia/Kolkata'                    AS valid_to,
               round(exp(sum(log_price_factor) OVER later), 12)                  AS price_factor,
               round(exp(sum(log_volume_factor) OVER later), 12)                 AS volume_factor
        FROM per_ex_date
        WINDOW later AS (ORDER BY ex_date DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
    )
    SELECT p."time",
           round(p.open  * coalesce(r.price_factor, 1), 4),
           round(p.high  * coalesce(r.price_factor, 1), 4),
           round(p.low   * coalesce(r.price_factor, 1), 4),
           round(p.close * coalesce(r.price_factor, 1), 4),
           round(p.volume * coalesce(r.volume_factor, 1))::bigint,
           p.oi,
           coalesce(r.price_factor, 1),
           p.source_id
    FROM unified.price_history p
    LEFT JOIN ranges r
           ON p."time" >= r.valid_from
          AND p."time" <  r.valid_to
    WHERE p.instrument_id = p_instrument_id
      AND p."interval" = p_interval
      AND p."time" >= p_from
      AND p."time" <  p_to
    ORDER BY p."time"
$$;
