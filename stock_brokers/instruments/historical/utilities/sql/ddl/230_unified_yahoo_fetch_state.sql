-- Where the Yahoo Finance fetch has got to, one row per instrument.
--
-- The first full fetch is roughly eleven thousand tickers at about one request a second, and Yahoo
-- rate limits, so it has to be resumable. After that it drives which tickers are refreshed: those
-- with a fresh raw price gap or token change, and a rotating slice of the rest.

CREATE TABLE IF NOT EXISTS unified.yahoo_fetch_state (
    instrument_id    UUID        PRIMARY KEY REFERENCES unified.instruments (instrument_id),
    yahoo_symbol     TEXT,
    -- 'ticker' for SYMBOL.NS or SYMBOL.BO, 'scrip_code' for the BSE scrip code form such as 506854.BO.
    symbol_kind      TEXT        CHECK (symbol_kind IN ('ticker', 'scrip_code')),
    last_fetched_at  TIMESTAMPTZ,
    last_status      TEXT        CHECK (last_status IN ('ok', 'empty', 'mismatch', 'error')),
    last_error       TEXT,
    history_start    DATE,
    history_end      DATE,
    last_event_date  DATE
);

CREATE INDEX IF NOT EXISTS yahoo_fetch_state_due_idx
    ON unified.yahoo_fetch_state (last_fetched_at NULLS FIRST);

-- 'nse_ticker': a BSE instrument read through its NSE listing's ticker, for companies whose BSE
-- tickers Yahoo keeps only as stubs (PIDILITIND.BO and 500331.BO return one row and none). The
-- corporate actions are the company's, so they are the same on both exchanges.
ALTER TABLE unified.yahoo_fetch_state DROP CONSTRAINT IF EXISTS yahoo_fetch_state_symbol_kind_check;
ALTER TABLE unified.yahoo_fetch_state ADD CONSTRAINT yahoo_fetch_state_symbol_kind_check
    CHECK (symbol_kind IN ('ticker', 'scrip_code', 'nse_ticker'));
