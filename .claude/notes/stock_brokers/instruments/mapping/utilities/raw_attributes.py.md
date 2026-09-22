# Notes on `stock_brokers/instruments/mapping/utilities/raw_attributes.py`

## Why the attributes are read at mapping time rather than joined later

The obvious design is to leave the extra columns where they already are, in `<broker>.instruments`, and join back to them when `/api/instruments/additional_details` is asked. The comment on `unified.broker_mappings` even invites it: "`broker_token` is also the join key back into that broker's own raw snapshot in `<broker>.instruments`, so any column the mapping does not carry is one lookup away."

That turns out not to hold in general. A broker's token is not unique within one day's snapshot for seven of the ten brokers. Counting today's files on 2026-09-22:

| Broker | Rows | Distinct tokens | Token alone identifies a row |
| --- | --- | --- | --- |
| Fyers | 163,449 | 163,449 | yes |
| INDmoney | 106,939 | 106,939 | yes |
| Zerodha | 113,796 | 113,796 | yes |
| Dhan | 207,159 | 196,001 | no |
| Kotak | 195,324 | 183,168 | no |
| Groww | 139,000 | 129,337 | no |
| Stoxkart | 468,408 | 448,292 | no |
| Wisdom Capital | 186,934 | 176,982 | no |
| Flattrade | 156,570 | 154,922 | no |
| Shoonya | 169,815 | 167,504 | no |

Adding the broker's own exchange and segment columns fixes six of those seven exactly, but `unified.broker_mappings` stores no broker-side exchange or segment column to join on. The symbol columns it does store are no help either, because `broker_symbol` is configured per segment and changes within a broker: Dhan uses `display_name` in some segments and `symbol_name` in others, Kotak uses `pdesc` and `ptrdsymbol`, Groww uses `name` and `trading_symbol`.

Flattrade would still not resolve even with an exchange column. Its BSE file lists the same token under several trading symbols, which looks like renamed scrips kept under both the old and the new name:

```text
BSE  token=539175  copies=3  BLUEGOD | INDRAIND | STARBEAM
BSE  token=522275  copies=3  GET&D   | GVT&D    | GVTD
BSE  token=500215  copies=2  ATFL    | SUNDROP
```

`BrokerMappingAdapter.run` already holds the exact raw row that produced each mapping row, so reading the attributes there sidesteps the whole problem. There is no key to get wrong, and a re-run of the mapping refreshes the attributes with everything else.

`MappingResolver.raw_row` still joins on the token alone. It has no callers, so nothing is broken today, but it would return a row from the wrong exchange or segment for those seven brokers if one were added.

## Why the attributes are a column on the mapping table rather than their own table

The grain is identical: one row per instrument, broker and mapping date, which is exactly the primary key of `unified.broker_mappings`. A separate table would repeat that key and add a join for no gain. The project's DDL rules explicitly allow adding a column by appending `ALTER TABLE … ADD COLUMN IF NOT EXISTS` to the table's existing file, which is what `120_unified_broker_mappings.sql` now does.

The column is `JSONB` rather than sixteen typed columns because the set of attributes is expected to grow as brokers are looked at more closely, and because every value is text in the source anyway — a raw instrument table stores every column as `TEXT`, and nothing here is a number the system computes with.

`stream_order_handles` and the other readers name their columns explicitly, so the order path does not read the new column and does not get slower.

## Why the vocabulary is shared rather than each broker's own spelling

The same decision the tick, order and position contracts make. A caller comparing brokers should not have to know that Dhan says `isin`, Kotak says `pisin` and Stoxkart says `isin_code`, or that a freeze quantity is `sm_freeze_qty`, `lfreezeqty`, `freeze_quantity`, `freezeqty` and `freeze_qty` depending on who is asked.

Every name in `ATTRIBUTE_NAMES` is present for every broker, with `None` where that broker publishes nothing, so a caller can index the answer without checking first. Values are otherwise untouched: stripped of surrounding whitespace, turned into text, and never converted, scaled or corrected. A broker that reports a price band in paise still reports it in paise here.

## Why storage holds only what a broker published

`RawAttributes.extract` leaves an attribute out entirely rather than storing it as null, and `RawAttributes.fill` puts the missing names back when the endpoint answers. The two shapes are deliberately different, and the reason is measured rather than theoretical.

The first version stored all sixteen names for every broker, nulls included. Warmed for 2026-09-22 across all ten brokers that came to 888 MB in Redis, against an estimate of about 250 MB:

| Hash | Fields | Memory | Per field |
| --- | --- | --- | --- |
| `identity` | 532,002 | 202.8 MB | 400 B |
| `order_handles` | 532,002 | 264.2 MB | 521 B |
| `additional_attributes`, nulls stored | 531,997 | 887.9 MB | 1,750 B |
| `additional_attributes`, nulls dropped | 531,997 | 306.4 MB | 604 B |

The overshoot is all key names. An instrument is carried by 3.53 brokers on average, so storing sixteen names each means about 56 copies of strings like `margin_trading_leverage` per instrument, most of them pointing at null. Dropping them costs nothing at the API boundary, because the endpoint was already reading through `.get()` and filling absent names with null.

A row where a broker published nothing at all stores SQL `NULL` in the column, and `stream_additional_attributes` skips those rows, so they cost nothing in Redis either. Four brokers publish very little: Flattrade contributes only an instrument type, Shoonya an instrument type and a multiplier, Zerodha a name and an instrument type.

## Values are stored as sent, sentinels included

The first answer for NSE INFY on 2026-09-22 showed several brokers sending placeholder values rather than real ones, and every one of them is passed through untouched:

| Broker | Attribute | Value | What it appears to be |
| --- | --- | --- | --- |
| Kotak | `price_band_high` | `114230` | Rupees expressed in paise, against Dhan's `1156.5000` |
| Kotak | `multiplier` | `-1` | A "no value" sentinel, the same shape as the tick sizes of `0` and `-1` |
| Kotak | `permitted_to_trade` | `0` | Reads as "not permitted" for a liquid NSE equity, so it is probably not the flag its name suggests |
| INDmoney | `multiplier` | `0` | A "no value" sentinel |
| Wisdom Capital | `surveillance_category` | `-1` | A "no value" sentinel |
| Fyers, Wisdom Capital | `instrument_type` | `0`, `8` | Numeric codes rather than the text the other brokers send |

Nothing here is corrected, which is the rule everywhere in this project. The tick size is the one existing exception, and it is handled in `to_broker_fields` because an order's price is checked against it. No consumer computes with these attributes yet, so none of them has earned the same treatment. A caller comparing a price band across brokers has to know that Kotak's is in paise.

## How the attribute set was chosen

The measured criterion was that several brokers supply the attribute and that it answers a question the API could not answer before. Coverage of the raw columns on 2026-09-22:

| Attribute | Brokers | Notes |
| --- | --- | --- |
| `instrument_type` | 10 | The broker's own classification of the row |
| `display_name` | 8 | A readable company or contract name; the API otherwise returns only tickers |
| `isin` | 7 | About 11 to 14 per cent of rows, which is essentially all the securities; derivatives have none |
| `series`, `freeze_quantity` | 5 | Freeze quantity is filled on 91 to 100 per cent of rows where it exists |
| `price_band_high`, `price_band_low`, `multiplier`, `underlying_token` | 4 | Price bands are filled on essentially every row |
| `surveillance_category` | 3 | Dhan's ASM and GSM category, Kotak's surveillance message, Wisdom Capital's GSM indicator |
| `pledge_eligible` | 2 | |
| `permitted_to_trade`, `buy_allowed`, `sell_allowed`, `intraday_leverage`, `margin_trading_leverage` | 1 | Single-broker, kept because they answer funding and tradability questions nothing else does |

Whole raw rows were considered and rejected on size. The payload alone came to 1.14 GB across the ten brokers, which at the roughly 1.7 times overhead the existing hashes show would have put about 1.9 GB into Redis, against the 306 MB the curated set actually costs. The rejected columns are mostly noise for a caller anyway, such as Kotak's `pcurrectiontime` and Fyers' `reserved_column1`.
