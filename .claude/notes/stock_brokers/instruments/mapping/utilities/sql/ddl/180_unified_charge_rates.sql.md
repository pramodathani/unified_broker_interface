# 180_unified_charge_rates.sql

Added on 2026-10-19 as the first stage of a real breakeven for protective stops, after a day of 178 NIFTY option round trips at Flattrade paid 4,857.20 of statutory charges against a trading loss of 1,257.75.

## Where the seeded rates come from

- **STT** is the Finance Act 2026 rate from 1 April 2026: 0.15% on option sales and 0.05% on futures sales (up from 0.1% and 0.02%). Equity delivery (0.1% both sides) and intraday (0.025% on sales) did not change. Sources: ICICI Direct and Groww articles on Budget 2026, and NSE circular NSE/FATAX/73524.
- **Exchange charges** are from Flattrade's knowledge-base page "What are exchange transaction charges", posted 9 April 2026: NSE equity 0.00307%, futures 0.00183%, options 0.03553%; BSE equity 0.00375%, options 0.0325%, futures 0. They are the older 0.00297%, 0.00173% and 0.03503% plus the investor protection fund charge that NSE circular NSE/FA/73061 folded into the transaction charge on 1 March 2026. The options figure matches the 1,456.24 on Flattrade's bill FO20261019 exactly (0.03553% of 40,98,623.75).
- **Stamp duty** is the Indian Stamp Act rate for each instrument: 0.015% delivery, 0.003% intraday and options, 0.002% futures, on the buyer only.
- **SEBI fee** is 10 rupees a crore, 0.0001%, on both sides. **GST** is 18% on the exchange charge, the SEBI fee and brokerage.

Only `nse_equity_index_options` has `checked_on`, because only it was checked against a bill. BSE futures were left out rather than seeded with a zero exchange charge nobody had checked. MCX, currency and exchange-traded fund rows were left out because their rates (CTT on commodities, no STT on currency, the ETF rules) were not confirmed from a current source; a missing row makes `ChargeRateTable.rate` answer None, which is safer than a wrong rate.

## Checked on 2026-10-19

Applied with `python -m stock_brokers.instruments.mapping.utilities.sql.apply_ddl`; the table read back 10 rows, and the option row gave the bill's exchange charge, SEBI fee and GST to the paisa.
