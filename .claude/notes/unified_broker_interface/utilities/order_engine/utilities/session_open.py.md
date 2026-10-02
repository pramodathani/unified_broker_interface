# session_open.py

Added on 2026-10-02 because both VWAPs hard-coded NSE's 09:15 open: an MCX VWAP after about 15:45 quietly weighted every slice alike (TWAP), a caller's MCX profile was shifted by fifteen minutes, and a slice after midnight wrapped to the morning's first bucket.

It reuses the two existing sources rather than adding a third table: `sessions.session_for` to sort a segment into the equity, currency or commodity calendar (its `opens` field is the tick window, 09:00 for every segment, so it is not used for the open), and `exchange_calendar.TRADING_HOURS` for the first session's real opening time. A missing or empty segment is taken as equity so instruments without one behave as before.

The user agreed (2026-10-02) that a currency or commodity VWAP with no `volume_profile` gets even slices rather than the equity curve, since there is no measured curve for those markets yet; a refusal was the alternative and was not chosen.
