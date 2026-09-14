-- Every broker series that feeds unified.price_history, and how it was matched to its instrument.
--
-- One row per broker series, interval and instrument. It is the provenance of every bar (a bar's
-- source_id points here) and the loader's resume point (the progress snapshot and the watermarks).
--
-- A series is resolved once, not bar by bar. `resolved_by` says how:
--   broker_mapping  the broker's own token found the instrument in unified.broker_mappings
--   exchange_token  the token did not, but other brokers mapping the same exchange token agreed
--   raw_symbol      neither did, and the trading symbol matched unified.instruments
--   manual          set by a person
--
-- Stitching: one instrument can have several series at one broker - INDIAGLYCO moved from EQ
-- (token 1521) to BE (token 7128) on 2026-09-02, and flattrade keeps both. The loader gives each
-- trading day to the newest series that has it; `owned_from` and `owned_to` record the result.

CREATE TABLE IF NOT EXISTS unified.price_history_sources (
    source_id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker                TEXT        NOT NULL,
    broker_series         TEXT        NOT NULL,
    "interval"            TEXT        NOT NULL,
    instrument_id         UUID        NOT NULL REFERENCES unified.instruments (instrument_id),
    resolved_by           TEXT        NOT NULL
        CHECK (resolved_by IN ('broker_mapping', 'exchange_token', 'raw_symbol', 'manual')),
    mapping_first_date    DATE,
    mapping_last_date     DATE,
    -- 'unadjusted' for equities, exchange traded funds and investment trusts from a source verified
    -- to serve raw prices; 'as_served' for everything else.
    price_basis           TEXT        NOT NULL CHECK (price_basis IN ('unadjusted', 'as_served')),
    role                  TEXT        NOT NULL CHECK (role IN ('primary', 'gap_fill')),
    status                TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'ambiguous', 'rejected', 'superseded')),
    status_reason         TEXT,
    owned_from            TIMESTAMPTZ,
    owned_to              TIMESTAMPTZ,
    -- The broker's progress row as last seen, so a later run can tell whether the series grew.
    broker_earliest_seen  TIMESTAMPTZ,
    broker_latest_seen    TIMESTAMPTZ,
    loaded_earliest       TIMESTAMPTZ,
    loaded_latest         TIMESTAMPTZ,
    last_loaded_at        TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (broker, broker_series, "interval", instrument_id)
);

CREATE INDEX IF NOT EXISTS price_history_sources_series_idx
    ON unified.price_history_sources (instrument_id, "interval", role, status);
