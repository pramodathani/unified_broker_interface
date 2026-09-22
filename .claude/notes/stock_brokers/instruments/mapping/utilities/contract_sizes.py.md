# Notes on `stock_brokers/instruments/mapping/utilities/contract_sizes.py`

## Why contract sizes are decided in the morning

On 2026-09-15 the user said currency and commodity segments had to be enabled for trading, and asked for the lot size problem to be handled at the beginning of the day, so that the numbers are trusted and nothing is decided at run time. The problem was that brokers' own `lot_size` figures mean different things on these markets. The earlier `units_per_lot` rule in `stock_brokers/instruments/ticks/utilities/resolution.py`, which the unified quotes and `/api/instruments/details` use, takes Groww's figure on MCX and the brokers' majority elsewhere; checked against live contracts that day, the majority rule gave NSE USDINR a lot of 1 (five brokers counting lots against Stoxkart's 1000), and the brokers disagreed on 99% of live NSE currency options and every NSE commodity option. That rule is left as it is for quotes; orders use this module instead.

## Where the sources came from

The raw `<broker>.instruments` tables were searched for fields that state a contract's size, and each candidate was compared contract by contract on 2026-09-15:

| Contract | Wisdom Capital `multiplier` | Kotak `llotsize × dgennum ÷ dgenden` | Groww `lot_size` | Kotak units |
| --- | --- | --- | --- | --- |
| MCX CRUDEOIL | 100 | 100 × 1 ÷ 1 | 100 | BBL |
| MCX GOLD | 100 | 1 × 100 ÷ 1 | 100 | trades in KGS, priced per 10 GRMS |
| MCX GOLDM | 10 | 100 × 1 ÷ 10 | 10 | GRMS, priced per 10 GRMS |
| MCX SILVERM | 5 | 5 × 1 ÷ 1 | 5 | KGS |
| MCX NATURALGAS | 1250 | 1250 × 1 ÷ 1 | 1250 | mmBtu |

On NSE currencies Kotak gives `llotsize` 1 with `lmultiplier` 1000, Shoonya `lotsize` 1 with `multiplier` 1000, and Stoxkart `lot_size` 1000. Shoonya's and Stoxkart's MCX lot sizes are in the exchange's trading unit (GOLD 1, one kilogram), not the quotation unit, so they are sources only on the currency segments.

Across every live contract that day: all 15,887 MCX contracts covered by a source had two or three agreeing sources; NSE commodities had 24,969 agreeing, 12 conflicts (SILVER100 futures, Kotak 100 against Wisdom Capital and Groww 1) and one single-source test contract; NSE currencies had 11,064 agreeing and 9 conflicts (GBPINR and JPYINR options, Stoxkart 2000 against Kotak and Shoonya 1000). BSE currencies and NCDEX had Stoxkart only. 16,100 MCX options listed only by Stoxkart and 302 NSE currency options listed only by Flattrade had no source; the Flattrade ones are strikes Flattrade rounds to two decimals, which the mapping treats as separate instruments.

Each source is read with the raw exchange label it is trusted on, because a broker token is not unique across a broker's exchanges: a Stoxkart token matched both an NCDEX contract and an NSE option on the same date.

## The trust rule, as the user chose it

On 2026-09-15 the user chose, from options put to them: a contract is trusted when at least two sources give a size and all of them agree, so one disagreeing source makes a conflict even against two; and BSE currencies and NCDEX are traded on Stoxkart's figure alone rather than kept closed. The user was told that Stoxkart's NCDEX figures may be in tonnes rather than quintals. `ContractSizeDecision.SINGLE_SOURCE_MARKETS` holds that second choice, and `test_runs/contract_sizes.py` checks the rule.

`tradeable` is stored rather than worked out when an order arrives, so that the order route only reads a decision.

## Robustness

Snapshot columns are read through a regular expression before being cast, because the raw tables store text and a single malformed value would otherwise abort the whole query. A size that is zero or negative is treated as missing, which matters for Kotak, whose `lmultiplier` is -1 where it has none. `bin/unified/instruments/map` logs a failure of this step and carries on, because the safe outcome of a missing decision is already that such orders are refused.

The run took 12 seconds on 2026-09-15 and wrote 83,351 rows.
