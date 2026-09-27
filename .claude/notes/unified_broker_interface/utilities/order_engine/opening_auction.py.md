# Notes on `unified_broker_interface/utilities/order_engine/opening_auction.py`

## Where the times come from

The collection times are the ones the Atlas quotes from Zerodha's help page for the rules effective 7 September 2026: market and limit orders until 09:05, limit orders alone until 09:10, and matching from 09:10 to 09:12. NSE's futures pre-open began on 8 December 2025 for current-month stock and index futures, and closes its collection at a random moment between 09:07 and 09:08. They are constants on the class rather than read from `exchange_calendar.py`, because the calendar records only the pre-open's start and end (09:00 to 09:15), not the collection windows inside it, and because they change by exchange circular rather than by year.

## Why a late order is refused rather than sent

An order that misses collection would still be accepted by the broker, and would trade in the first seconds of continuous trading at whatever the book offers then. That is a different order from one that fills at the auction's single price, and the caller asked for the auction. The Atlas's suggested approximation for instruments without a pre-open, a scheduled order at 09:15, is named in the refusal so the caller can choose it knowingly.

## Why the month of a future is not checked

Only current-month futures have a pre-open, but the instrument identity does not say which expiry is the current month without comparing it with the other expiries listed that day. A later-month future is sent, and the broker or exchange decides what to do with it. This is written in the docs so it is not a surprise.

## Why `Scheduled` gained `read_place_at`

`Scheduled.run` read `at_time` inline. The opening auction needs the same recording, answer and clock handling with a different rule for the time, so the time was moved into one method that this class overrides. The scheduled order's answers are unchanged, which the recorded scenarios confirm.
