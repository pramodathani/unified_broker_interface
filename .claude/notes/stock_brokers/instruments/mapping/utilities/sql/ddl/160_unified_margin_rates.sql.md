# Notes on `stock_brokers/instruments/mapping/utilities/sql/ddl/160_unified_margin_rates.sql`

`unified.margin_rates` holds the exchange's margin as a share of a contract's value, per catalogue segment and optionally per underlying. The lowest-cost selector's `MarginEstimate` reads it through `MarginRateTable` to work out, without calling any broker, how much margin an order will need.

`span_rate` is SPAN for a derivative and the VaR margin for an intraday equity order; `exposure_rate` is the exposure margin (ELM). A future needs `span_rate + exposure_rate` of its value; a sold option needs the same share of its underlying's value; a hedged set of option legs needs its maximum loss plus `exposure_rate` of each short leg's underlying value.

A row with `underlying = ''` is the fallback for every underlying in that segment, and a row naming an underlying (the catalogue's `underlying_symbol`, such as `NIFTY`) overrides it. The fallbacks are deliberately high, because an estimate that is too high only passes over a broker that could have taken the order, while one that is too low sends an order the broker will reject: index derivatives 12% plus 3%, stock derivatives 35% plus 5% (single stocks range from about 15% to 40%), commodities 45% plus 2% (natural gas runs close to that; gold is far lower), currencies 5% plus 2%, and intraday equities 20%, which is SEBI's floor of five times leverage.

The two named rows were measured on 2026-09-30: NIFTY futures needed SPAN 137,425.60 and exposure 29,683.81 on a contract worth 22,833.7 × 65, which is 9.26% and 2.00%; crude oil futures needed SPAN 260,300 and exposure 10,772.50 on 8,618 × 100, which is 30.2% and 1.25%. Every broker that reports the split gave the same figures to the rupee.

The rows are meant to be replaced by a daily download of the exchanges' SPAN and VaR files; until that exists they are edited by hand. The seed does nothing on conflict so those edits survive the morning run.
