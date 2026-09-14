-- Historical candles for fyers, exactly as the broker serves them.
--
-- One row per instrument, interval and bar. The interval is a column rather than a table per
-- interval because a broker's interval set is its own business and changes without notice; a
-- new one then needs no DDL. Candles are stored as received - nothing is derived here, so a
-- five minute bar is the broker's five minute bar and not six one minute bars added up.
--
-- fyers serves history from around 2017.

CREATE TABLE IF NOT EXISTS fyers.price_history (
    "time"            TIMESTAMPTZ   NOT NULL,
    instrument_token  TEXT          NOT NULL,
    "interval"        TEXT          NOT NULL,
    open              NUMERIC(18,4),
    high              NUMERIC(18,4),
    low               NUMERIC(18,4),
    close             NUMERIC(18,4),
    volume            BIGINT,
    oi                BIGINT,
    downloaded_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    -- The bar is identified by instrument, interval and time, so re-fetching a window updates
    -- rather than duplicates. A backfill that is interrupted and resumed overlaps by design.
    PRIMARY KEY (instrument_token, "interval", "time")
);

-- One month chunks. This was seven days first, and measurement said otherwise: daily bars back
-- two decades spread across 7-day chunks gave 1,133 chunks holding 98 rows each for a single
-- instrument, where per-chunk overhead dwarfed the data and 111,000 bars occupied 75 MB. One
-- table holding both minute and daily bars has to pick one chunk size for two very different
-- densities, and the sparse series is the one that suffers from chunks that are too small.
SELECT create_hypertable(
    'fyers.price_history',
    by_range('time', INTERVAL '1 month'),
    if_not_exists => TRUE
);

-- Compressed by instrument and interval, which is how the data is read: one instrument's series
-- over a date range. Thirty days leaves the recent window uncompressed for the incremental
-- download to keep appending to.
ALTER TABLE fyers.price_history SET (
    timescaledb.enable_columnstore = true,
    timescaledb.segmentby = 'instrument_token, "interval"',
    timescaledb.orderby = '"time" DESC'
);

-- A procedure rather than a function in TimescaleDB 2.x, so CALL and not SELECT.
CALL add_columnstore_policy(
    'fyers.price_history',
    after => INTERVAL '30 days',
    if_not_exists => TRUE
);

-- Where the downloader has got to for every instrument and interval it knows about. A plain
-- table, not a hypertable: it is current state, one row per series, read and updated constantly.
--
-- A backfill of this size is measured in weeks and will be interrupted many times, so the
-- watermark and the bars it accounts for are written in one transaction. Losing the process
-- costs at most the window in flight, and repeating that window is harmless because the bars
-- upsert.
CREATE TABLE IF NOT EXISTS fyers.price_history_progress (
    instrument_token      TEXT      NOT NULL,
    "interval"            TEXT      NOT NULL,
    -- The span already stored. Incremental work resumes from latest_bar_time, backfill walks
    -- backwards from oldest_requested_time.
    earliest_bar_time     TIMESTAMPTZ,
    latest_bar_time       TIMESTAMPTZ,
    oldest_requested_time TIMESTAMPTZ,
    -- Set when the broker refuses to go back further, so the series stops being asked. An
    -- expired contract answers 'invalid token' rather than an empty window, and without this the
    -- queue would ask again forever.
    reached_broker_limit  BOOLEAN   NOT NULL DEFAULT FALSE,
    limit_reason          TEXT,
    bar_count             BIGINT    NOT NULL DEFAULT 0,
    empty_window_streak   INTEGER   NOT NULL DEFAULT 0,
    last_attempt_at       TIMESTAMPTZ,
    last_outcome          TEXT,
    last_failure_reason   TEXT,
    consecutive_failures  INTEGER   NOT NULL DEFAULT 0,
    -- Exponential backoff, so a series that keeps failing stops crowding out the queue.
    next_attempt_after    TIMESTAMPTZ,
    -- Lower is worked first. Cash daily bars land the first night; expired option minute bars
    -- drain last, which is the difference between useful data in days and useful data in months.
    priority              INTEGER   NOT NULL DEFAULT 100,
    seeded_date           DATE,
    PRIMARY KEY (instrument_token, "interval")
);

-- The claim query: the next due series in priority order, skipping what is finished or backing
-- off. Partial, because the finished rows are the majority once a backfill matures.
CREATE INDEX IF NOT EXISTS price_history_progress_claim_fyers
    ON fyers.price_history_progress (priority, next_attempt_after NULLS FIRST)
    WHERE reached_broker_limit = FALSE;

CREATE INDEX IF NOT EXISTS price_history_progress_outcome_fyers
    ON fyers.price_history_progress (last_outcome, last_attempt_at DESC);
