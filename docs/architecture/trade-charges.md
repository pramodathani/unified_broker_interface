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

## The tripwire

The real breakeven is the floor of a protective stop, not its trigger. A stop does not sell at its trigger: it fires once the price has crossed it and fills at the next price, a little beyond. On 19 October 2026, 60 of 83 stops whose trigger was the entry price filled below it. A stop whose trigger is the floor would lose the same slip, so the trigger, the **tripwire**, has to sit beyond the floor by as much as stops usually slip.

### Measuring the slip

`bin/unified/orders/stop_slippage` follows every protective stop that fired to the fill that closed its position, and writes one row per stop to `unified.stop_slippage`. A protective stop is a `plan` whose order has `side` `protect` and a `price_crosses` trigger, which every held stop and every routed stop type becomes in the engine. The close is one of three things:

| `closed_by` | What closed the position | Why it counts |
|---|---|---|
| `stop` | The stop's own order filled, as the event log or, when the engine never saw the fill, the broker's saved record in `unified.daily_orders` says | The ordinary case; a stop the strategy cancelled just as it filled is a fill only the broker recorded |
| `other_order` | The stop did not fill, and the strategy's next order on the same instrument and side, requested within a minute, did | A strategy closes the position itself when its stop does not fill, and those closes are the furthest from the trigger; leaving them out would make stops look better than they are |
| empty | No fill was found | Written with an empty slip and left out of the figures |

The slip is the close's distance beyond the trigger, positive when worse, in rupees per unit (`slip`) and in basis points of the trigger (`slip_basis_points`). Basis points let one figure serve every price in a segment.

The run over the week to 19 October 2026, after the day's orders were saved, printed the figures below.

```text
segment                      side   fired  by stop  by other  unresolved  median bps  90th bps
nse_equity_index_options     BUY        1        0         0           1        None      None
nse_equity_index_options     SELL     269      177        48          44       15.91     69.93
```

On 19 October, whose orders are saved in `unified.daily_orders`, 149 of the 173 sell stops filled themselves, 39 of them known only from the broker's record, 18 were closed by the strategy's own sell, and 6 stayed unresolved: 3 were refused by Flattrade for want of margin, because the position had already been closed and the sale would have opened a short one, 2 never reached the broker, and 1 was refused as it was being cancelled. Without the broker's records, 26 of those stops had been matched to the next trade's sell instead, because the strategy trades seconds apart. The 38 unresolved stops of the days before were not saved, because `bin/unified/orders/store_daily_orders` did not yet exist.

### The allowance

`StopSlipAllowance` reads the last 20 days of `unified.stop_slippage` and gives, for a segment and side, a percentile of the measured slips. The 90th percentile, the default, is the slip nine stops in ten stayed within. A segment and side with fewer than 30 measured stops has no allowance, because a handful of stops says little about the next one.

### The trigger

`TripwirePrice` places the trigger so that a fill slipping by the whole allowance still lands on the floor. For a bought position,

```text
trigger × (1 − allowance) = floor
```

and a sold position mirrors it, with its trigger below the floor. With no allowance, the trigger is the floor plus the live spread and two ticks instead. Either way it is rounded to the tick away from the floor. The table below shows the levels for 65 NIFTY option units bought at 177.00 at Flattrade, with the slips of 19 October.

| Allowance | Basis points | Floor | Tripwire | From the entry |
|---|---|---|---|---|
| 50th percentile | 14.76 | 177.45 | 177.75 | +0.75 |
| 90th percentile, the default | 56.36 | 177.45 | **178.50** | **+1.50** |
| 95th percentile | 72.12 | 177.45 | 178.75 | +1.75 |
| No measured slip, spread 0.20 | | 177.45 | 177.75 | +0.75 |

The higher the percentile, the more exits land on the floor, but the further the price must rise before the stop can sit at the tripwire at all, so fewer trades are protected by it.

## The switch-on

A stop moved to its tripwire the moment the price reaches it is fired by the next ordinary wobble. The **switch-on** is the price the watched side, the bid for a bought position and the ask for a sold one, must reach before the stop is moved to the tripwire. It sits beyond the tripwire by the instrument's **flicker**: for each of the last 30 minutes of ticks, how far the watched price moved against the position within the next 5 seconds, and the 90th percentile of those moves. `PriceFlicker` measures it from `unified.ticks`, and `SwitchOnPrice` places the level, rounded to the tick away from the tripwire. Without 30 measured moves it falls back to the spread plus two ticks.

On 19 October 2026, the bid of the NIFTY 27 October 22850 call fell by 0.10 or less within five seconds at the median and by 0.80 or less nine times in ten, and the 22900 put's by 0.85.

## Asking for the levels

`GET /api/instruments/breakeven` answers all three levels for one position: the instrument, the entry price, the quantity, the side, the product and, optionally, the broker. [Breakeven levels](../rest-api/breakeven.md) documents it. `BreakevenLevels` does the work: it reads the charge rates, the broker costs and the stop slips on the first request of each day and keeps them, reads the flicker on every request, and takes the spread from the live quote. The table below shows its answer for 65 units of the 22850 call bought at 177.00 at Flattrade, on the night of 19 October, with the week's stops.

| Level | Price | From the entry | Worked out from |
|---|---|---|---|
| Floor | 177.45 | +0.45 | The charge rates, checked against the bill of 19 October |
| Tripwire | 178.70 | +1.70 | 225 measured sell stops, 90th percentile slip 69.93 basis points |
| Switch-on | 179.50 | +2.50 | 2,247 ticks, 90th percentile five-second fall 0.80 |

A strategy using them buys at 177.00, waits for the bid to reach 179.50, then moves its stop to 178.70. Nine stops in ten that then fire close at 177.45 or better, which nets nothing or more after every charge.

Nothing on the order path reads these levels yet; a strategy asks for them and moves its own stop.
