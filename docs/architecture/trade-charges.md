# Trade charges and the real breakeven

A broker that charges no brokerage still sends a bill. Every trade also pays securities transaction tax (STT), the exchange's transaction charge, SEBI's turnover fee, stamp duty and GST, which the broker collects for the government and the exchange. On 19 October 2026, 178 round trips in NIFTY options at Flattrade paid no brokerage and 4,857.20 rupees of these charges, almost four times the 1,257.75 the trades lost before them.

This page describes how those charges are worked out before and after a trade, and how they give a position's **real breakeven**: the exit price at which it makes exactly nothing once everything is paid. A stop that moves "to breakeven" at the entry price loses the charges every time it fires; one at the real breakeven does not.

[Measuring execution costs](execution-costs.md) covers the other part of what a trade costs, the price moves and spread between deciding to trade and the fill.

## The charge rate table

Every rate comes from the PostgreSQL table `unified.charge_rates`, one row per segment and category. The category is decided as the [lowest-cost selector](broker-selection.md#how-an-orders-category-is-decided) decides it: `fno` for a future or an option with any product, `delivery` for a cash instrument with product `CNC`, and `intraday` for any other cash order. Brokerage is not in this table, because it differs by broker and is already kept in `unified.broker_order_costs`.

| Column | What it holds | Charged on |
|---|---|---|
| `stt_buy_rate` | STT | The value bought |
| `stt_sell_rate` | STT | The value sold |
| `exchange_rate` | The exchange's transaction charge | Both sides |
| `sebi_rate` | SEBI's turnover fee, 10 rupees a crore | Both sides |
| `stamp_buy_rate` | Stamp duty | The value bought |
| `gst_rate` | GST | The exchange charge, the SEBI fee and the brokerage, never STT or stamp duty |
| `checked_on` | The day the row was last checked against a broker's bill, or empty when it never has been | |

The table is created and seeded by `stock_brokers/instruments/mapping/utilities/sql/ddl/180_unified_charge_rates.sql`, which runs with the rest of the unified schema. Its seed uses `ON CONFLICT DO NOTHING`, so a row changed since is never overwritten. The seeded rows are below. The exchange charges are those Flattrade published on 9 April 2026, after NSE folded the investor protection fund charge into them on 1 March 2026, and the STT is the Finance Act 2026 rate from 1 April 2026.

| Segment | Category | STT buy | STT sell | Exchange | Stamp | Checked against a bill |
|---|---|---|---|---|---|---|
| `nse_equity_index_options`, `nse_equity_options` | `fno` | 0 | 0.15% | 0.03553% | 0.003% | Index options on 2026-10-19 |
| `nse_equity_index_futures`, `nse_equity_futures` | `fno` | 0 | 0.05% | 0.00183% | 0.002% | Never |
| `nse_equities` | `delivery` | 0.1% | 0.1% | 0.00307% | 0.015% | Never |
| `nse_equities` | `intraday` | 0 | 0.025% | 0.00307% | 0.003% | Never |
| `bse_equity_index_options`, `bse_equity_options` | `fno` | 0 | 0.15% | 0.0325% | 0.003% | Never |
| `bse_equities` | `delivery` | 0.1% | 0.1% | 0.00375% | 0.015% | Never |
| `bse_equities` | `intraday` | 0 | 0.025% | 0.00375% | 0.003% | Never |

Every row has a SEBI rate of 0.0001% and GST of 18%. Commodities, currencies and exchange-traded funds have no row yet, so their charges are not known and nothing guesses them. STT on an option exercised at expiry is charged on its intrinsic value instead of its premium, and is not covered.

A rate changes with a budget or an exchange circular, so a row is only as good as its last check. To correct one, or to mark it checked, update it in place:

```sql
UPDATE unified.charge_rates
SET stt_sell_rate = 0.0015,
    checked_on = '2026-10-19',
    updated_at = now()
WHERE segment = 'nse_equity_index_options'
  AND category = 'fno';
```

`ChargeRateTable` holds the table in memory. Like the margin rate table, building it reads nothing; `start` reads it once and starts a thread that reloads it every day at 06:00 IST, keeping the old rows when a reload fails. A segment with no row answers None.

## One day's charges against the bill

`TradeCharges` takes the rupees bought and sold in one segment, and the brokerage for every order, and works out each charge as a bill does. The table below sets its figures for 19 October 2026 beside Flattrade's bill (FO20261019) for the same fills, 20,49,940.75 bought and 20,48,683.00 sold.

| Charge | Worked out | Flattrade's bill |
|---|---|---|
| Brokerage | 0.00 | 0.00 |
| STT | 3,073.02 | 3,073.00 |
| NSE transaction charge | 1,456.24 | 1,456.24 |
| SEBI fee | 4.10 | 4.10 |
| Stamp duty | 61.50 | 61.00 |
| GST | 262.86 | 262.86 |
| **Total** | **4,857.72** | **4,857.20** |

The two lines that differ are the ones the bill rounds to the rupee, so the figures here are within a rupee of a bill for each such line, however many trades it covers.

## The real breakeven

`BreakevenPrice` works out, for one position, the exit price that leaves a profit of exactly zero. For a position opened by buying at an entry price, the sale at S breaks even when

```text
S × quantity × (1 − sell-side rate) = entry × quantity × (1 + buy-side rate) + 2 × brokerage per order × (1 + GST)
```

The buy-side rate is STT on buys, stamp duty, and the exchange charge and SEBI fee with their GST; the sell-side rate is STT on sells and the same exchange charge and SEBI fee. A position opened by selling mirrors it, and its breakeven is the highest buy-back price that still loses nothing. `price` rounds the answer to the tick on the safe side, up for a bought position and down for a sold one, so an exit at that price never loses.

The table below shows the breakeven of some positions.

| Position | Brokerage an order | Breakeven | From the entry |
|---|---|---|---|
| 65 NIFTY option units bought at 177.00 | 0 | 177.45 | +0.45 |
| The same, sold at 177.00 | 0 | 176.55 | −0.45 |
| 65 NIFTY option units bought at 177.00 | 20 | 178.15 | +1.15 |
| 1 share bought intraday at 500.00 | 20 | 547.40 | +9.48% |
| 1,000 shares bought intraday at 500.00 | 20 | 500.25 | +0.05% |

Flat brokerage is shared across the quantity, which is why the same 20 rupees an order moves one share's breakeven by almost a tenth and a thousand shares' by a twentieth of a percent. A breakeven must therefore be worked out for each position, never set as a fixed number of points.

## What comes next

The real breakeven is the floor of a protective stop. A stop that fires at the floor still sells a little below it, because it is sent once the price has crossed and fills at the next bid; on 19 October, 60 of 83 stops set at the entry price filled below it, by 0.30 a unit on average. The next stages build on this page:

1. A tripwire above the floor by the slip that stops in the same kind of instrument have shown, read from `unified.order_execution_costs`.
2. A switch-on distance above the tripwire, so ordinary price flicker does not fire the stop at once.
3. A route that answers all three levels for an instrument, entry, quantity, side, product and broker, so any strategy, and later the order engine's own stops, can use them.

Nothing on the order path reads the charge rate table yet.
