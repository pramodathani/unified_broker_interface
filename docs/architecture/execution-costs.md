# Measuring execution costs

Brokerage is only part of what an order costs. The price an order fills at is usually worse than the price the market showed when the decision to trade was made, because the price moves while the order travels, because crossing the spread costs half of it, and because a large order walks the book. On an order worth 5 lakh rupees, one basis point is 50 rupees, which is more than the 20 rupees of brokerage most brokers charge for it. [Choosing a broker by cost](broker-selection.md) compares brokers on brokerage alone, so this page describes how the other part is measured.

The measurement is the first stage of a longer plan, which the diagram below shows in full. The orange dots follow an order and what it leaves behind, and the blue dots follow what is learned from it and fed back. The lower row exists today: `bin/unified/orders/execution_costs` reads the order engine's event log and the stored quotes every night and writes `unified.order_execution_costs`, and `bin/unified/orders/latency_calibration` then turns that table into per-broker figures in `unified.broker_order_costs`. The [pre-trade estimate](#the-pre-trade-estimate) exists as a class and is checked against the measured orders, but nothing on the order path calls it yet, and the broker choice does not yet read the per-broker figures.

<figure class="diagram">
--8<-- "docs/assets/diagrams/execution-costs.svg"
<figcaption>The orange dots follow an order to its fills and into the execution cost table; the blue dots follow the figures learned from that table back into the cost table the broker choice reads. The measurement, the calibration and the estimate exist today; nothing on the order path uses the estimate or the figures yet.</figcaption>
</figure>

## What is measured

Every leg the order engine sent and got a fill for is measured against the **mid-price**, halfway between the best bid and the best ask, at the moment the decision to trade was made. That moment is the parent's arrival for its first leg, and the leg's own request for every later leg, such as a stop placed after an entry filled. The difference between the fill and that mid-price is the **total cost**, also called implementation shortfall. It is split into four parts that always add up to it, as the table below shows. Every part is signed so that a positive number is money lost.

| Part | Column | Price move it measures | Depends on the broker? |
|---|---|---|---|
| Delay | `delay_cost` | The mid-price from the decision to the engine sending the leg | No; this is the engine's own time, including any time a held or conditional order waited on purpose |
| Latency | `latency_cost` | The mid-price from sending to the broker's answer | **Yes** |
| Half spread | `half_spread_cost` | Half the spread when the broker answered | No |
| Beyond the touch | `beyond_touch_cost` | How far the fill was beyond the best price on its side when the broker answered | No |

The last part is market impact when it is positive, because the order took more than the best level held. It is negative when a resting order filled inside the spread, and then it cancels the half spread, so a limit order that waited at the bid and was filled there shows a total cost below zero.

### A worked example

The numbers below are the first case in `python -m test_runs.execution_costs`. A buy of 65 units of a NIFTY option arrived when the book was 238.00 bid and 238.50 ask. By the time the engine sent it the book had moved up one tick, and by the time the broker answered it had moved up another. It filled at an average of 238.90.

| Moment | Best bid | Best ask | Mid-price |
|---|---|---|---|
| Decision, 10:15:00.000 | 238.00 | 238.50 | 238.25 |
| Sent, 10:15:00.200 | 238.10 | 238.60 | 238.35 |
| Broker answered, 10:15:00.300 | 238.20 | 238.70 | 238.45 |

The cost per unit splits into its parts like this:

| Part | Working | Per unit |
|---|---|---|
| Delay | 238.35 − 238.25 | 0.10 |
| Latency | 238.45 − 238.35 | 0.10 |
| Half spread | (238.70 − 238.20) ÷ 2 | 0.25 |
| Beyond the touch | 238.90 − 238.70 | 0.20 |
| **Total** | 238.90 − 238.25 | **0.65** |

That is 27.28 basis points of the decision's mid-price, and 42.25 rupees on 65 units. For a sell, every price move counts the other way round, because a seller gains when the price rises.

## Where the numbers come from

Nothing on the order path changed to make this measurement. The order engine already writes every step of an order to `unified.synthetic_order_events` before acting on it, so the moments are known: `parent_received` gives the arrival, `leg_requested` the send, `leg_answered` the broker's answer, and the `leg_update` rows the fill quantity and average price. The quotes at those moments come from `unified.ticks`, which keeps five levels of the book for every instrument the unified quote feed carries.

For each moment, the script takes the latest tick with both sides of the book at or before it. A tick more than 60 seconds old counts as missing, and the parts that need it are left empty, but the leg is still written so that a gap in the quote feed shows up in the table. On 5 and 6 October 2026 every one of the 175 filled legs had all three quotes. The decision's quote was 0.73 seconds old at the median and 11.7 seconds at the oldest, and a lookup took about 5 milliseconds.

`total_cost_rupees` is filled in only for the securities markets: equities, fixed income, funds and their derivatives. Some brokers report a currency or commodity fill in lots rather than units, and the event log keeps the quantity as the broker reported it, so a rupee figure there would be wrong by the lot size. The basis points are right for every market.

## The table

`unified.order_execution_costs` has one row per filled leg. It is a TimescaleDB hypertable on `time`, which is when the leg was sent, with seven days to a chunk. The table below lists its columns.

| Column | Meaning |
|---|---|
| `time` | When the engine recorded the leg's request, just before sending it |
| `parent_order_id`, `leg_id` | Which leg of which parent, as in `unified.synthetic_order_events` |
| `synthetic_type`, `leg_role` | The parent's type and what the leg was for, such as `entry` or `stop` |
| `broker`, `instrument_id`, `segment` | Where it went and what it traded |
| `transaction_type`, `product`, `order_type`, `quantity`, `price` | The leg as it was sent; `quantity` is in units, and `price` is the limit price, empty for a market order |
| `filled_quantity`, `average_price` | The fill as the broker last reported it |
| `decided_at`, `answered_at` | The decision moment and the broker's answer |
| `decision_quote_time`, `send_quote_time`, `answer_quote_time` | When each tick used was received, empty when none was recent enough |
| `decision_mid`, `send_mid`, `answer_mid` | The mid-price at each moment |
| `delay_cost`, `latency_cost`, `half_spread_cost`, `beyond_touch_cost`, `total_cost` | The parts and the total, per unit |
| `total_cost_basis_points`, `latency_cost_basis_points` | The total and the latency as basis points of `decision_mid` |
| `total_cost_rupees` | The total times `filled_quantity`, for the securities markets only |
| `measured_at` | When the row was written |

The script replaces every row of the days it measures in one transaction, so running it again gives the same table. The query below compares the brokers over the last twenty days.

```sql
SELECT
    broker,
    count(*) AS legs,
    round(avg(total_cost_basis_points), 2) AS mean_total_bps,
    round(avg(latency_cost_basis_points), 2) AS mean_latency_bps,
    round(sum(total_cost_rupees), 2) AS total_rupees
FROM unified.order_execution_costs
WHERE "time" > now() - INTERVAL '20 days'
GROUP BY broker
ORDER BY broker;
```

## Running it

`unified-execution-costs.timer` runs the script at 23:50 IST from Monday to Friday, after MCX closes, and the same unit runs the [latency calibration](#the-latency-calibration) straight after it. By default the measurement covers today and yesterday in India's time zone, so a night the timer missed is caught up the next night.

```bash
bin/unified/orders/execution_costs                              # measure today and yesterday and write the rows
bin/unified/orders/execution_costs --dry-run                    # print each broker's figures without writing
bin/unified/orders/execution_costs --date 2026-10-06 --days 5   # five days ending on 6 October
```

The first run, on 6 October 2026, printed the figures below for the two days it measured.

```text
broker            legs  measured  median bps  mean bps  mean latency bps
flattrade          138       138        8.73     12.20             -0.23
zerodha             37        37        6.94    -12.29              1.35
```

Two days of fills are too few to say one broker is cheaper than the other. The median latency was zero at both brokers, because the mid-price rarely moves in the tenth of a second a broker takes to answer, which is why the script prints the mean beside it.

## The latency calibration

Of the four parts, only latency depends on which broker carried the order. `bin/unified/orders/latency_calibration` therefore turns the last 20 days of the table into one latency figure per broker and order category, and writes it beside the brokerage in `unified.broker_order_costs`. The categories are the ones the lowest-cost selector prices brokerage by: `fno` for a future or option, `delivery` for a `CNC` order, and `intraday` for anything else. The table below lists the columns it writes.

| Column | What it holds |
|---|---|
| `latency_cost_bps_intraday`, `latency_cost_bps_delivery`, `latency_cost_bps_fno` | The mean `latency_cost_basis_points` of the broker's legs in that category |
| `broker_answer_milliseconds` | The median time from sending a leg to the broker's answer |
| `latency_calibrated_at` | When the script last wrote any of them |

Two rules decide what is written.

1. **The mean over every leg, not the median.** While a broker answers, the mid-price usually does not move, so most legs have a latency cost of exactly zero and the cost comes from the few that do. The median is therefore almost always zero, and a mean that dropped the highest and lowest few legs was tried and came out as exactly zero for every broker, because it dropped the legs that carried the cost.
2. **At least 30 legs.** A figure with fewer legs behind it is not written, and the column keeps whatever it held. A broker with nothing measured is not touched at all.

The first run, on 6 October 2026 after ten days had been measured, printed the figures below. Six brokers had too few legs in every category to be written.

```text
broker            intraday legs   intraday bps   delivery legs   delivery bps        fno legs        fno bps  answer ms
dhan                         25           None               0           None               0           None       None
flattrade                   101           0.00               0           None              72          -0.44         54
groww                        29           None               0           None               0           None       None
indmoney                     20           None               0           None               0           None       None
kotak                        23           None               0           None               0           None       None
shoonya                      20           None               0           None               0           None       None
stoxkart                     21           None               0           None               0           None       None
wisdom_capital               90           0.00               0           None               0           None         88
zerodha                      17           None               0           None              37           1.35         67
```

**Nothing reads these columns yet.** The lowest-cost selector still ranks brokers on brokerage alone. Reading them is a change to which broker receives an order, so it waits until a few weeks of ordinary trading show whether the brokers' figures really differ. Most of the legs above come from one test session on 29 September.

```bash
bin/unified/orders/latency_calibration                    # work out and write the figures
bin/unified/orders/latency_calibration --dry-run          # print them without writing
bin/unified/orders/latency_calibration --window-days 40   # use forty days of legs instead of twenty
```

## The pre-trade estimate

The measurement says what orders cost after the fact. `PreTradeEstimate` says what an order will cost before it is sent, if it crosses the spread now. It works from the five visible levels of the book, and for any quantity beyond them it uses the square-root impact model. Like the measurement, it splits the cost per unit into parts that add up to the total.

| Part | What it is | Exact or modelled? |
|---|---|---|
| Half spread | From the mid-price to the best price on the other side | Exact for the book as it stands |
| Book walk | From that best price to the average of the visible levels the order takes, with any quantity beyond the last level counted at that level's price | Exact |
| Beyond the book | What the square-root model adds for the quantity beyond the last visible level, spread over the whole order | Modelled |

### A worked example

The numbers below are from `python -m test_runs.pre_trade_estimate`. The ask side of a NIFTY option's book shows 300 at 238.50, 450 at 238.60, 600 at 238.75, 1,000 at 239.00 and 800 at 239.25, with the best bid at 238.00, so the mid-price is 238.25.

| Order | Half spread | Book walk | Beyond the book | Total | Basis points |
|---|---|---|---|---|---|
| Buy 1,200 | 0.2500 | 0.1312 | 0 | 0.3812 | 16.00 |
| Buy 5,000 | 0.2500 | 0.5365 | 0.3708 | 1.1573 | 48.58 |

The buy of 1,200 takes 300 at 238.50, 450 at 238.60 and 450 at 238.75, for an average of 238.63125, so the book covers it and nothing is modelled. The buy of 5,000 empties the 3,150 visible units and leaves 1,850 beyond the last level. For those, the model adds coefficient × daily volatility × mid-price × √(1,850 ÷ average daily volume) a unit. With a coefficient of 1.0, a volatility of 9.8% and a million units a day, that is 1.0021 a unit for the 1,850, or 0.3708 a unit spread over all 5,000.

### The square-root model and its coefficient

The square-root model says that trading Q units of an instrument that trades V units a day, with daily volatility σ, moves the price by about Y × σ × √(Q ÷ V). It is the most widely used rule for market impact, and studies of many markets put Y near 1. The volatility is the standard deviation of the last 20 daily log returns, and V is the average volume of the same 20 days. Both come from the daily bars in `unified.price_history_adjusted`, so a stock split does not show up as a crash, and both need at least ten days.

**Y has not been fitted to this project's orders, because none of them has been big enough.** Of the 465 orders measured up to 6 October 2026, none needed more than the best price level, and the largest took 17% of the five visible levels. Y can only be fitted from orders that go beyond the visible book. It lives in the table `unified.impact_coefficients`, one row per asset class (`securities`, `currency` and `commodity`), seeded with 1.0, and its `fitted_at` stays empty until it is fitted. When the model is needed but the volatility, the volume or the coefficient is missing, the estimate is left empty rather than guessed.

### How close it comes

`bin/unified/orders/estimate_check` runs the estimate on every measured order. It rebuilds the book at the order's decision from `unified.ticks` and sets the estimate beside the order's measured `half_spread_cost` plus `beyond_touch_cost`, which is the same cost without the price moving before and during sending. An estimate of crossing is only a fair prediction for an order that crossed, so crossing orders are summarised apart from resting ones. A crossing order is a market order, or a limit at or through the other side's best price at the decision. A stop order always counts as resting, because it waits for its trigger and fills later, against a book the decision never saw. The first run, on 6 October 2026, printed the following.

```text
legs        count  estimated  beyond book  mean estimate bps  mean actual bps  mean difference bps
crossing      426        426            0               6.11             5.81                 2.82
resting        29         29            0              12.28           -25.23                53.22
Impact coefficient for commodity: 1.0 (not fitted, textbook value)
Impact coefficient for currency: 1.0 (not fitted, textbook value)
Impact coefficient for securities: 1.0 (not fitted, textbook value)
```

For crossing orders, the estimate is close. Split by segment, the 337 equity orders averaged 3.78 basis points estimated against 3.83 actual, with 265 of them matching to the hundredth. The 89 index option orders averaged 14.92 estimated against 13.33 actual. The resting row shows why resting orders are kept apart: they are priced as if they crossed, but on average they earned a little of the spread instead of paying it. The `beyond book` column is zero for both, which is why the coefficient is still the textbook value.

```bash
bin/unified/orders/estimate_check             # check the last 20 days of measured orders
bin/unified/orders/estimate_check --days 40   # forty days instead
```

The script only reads, and has no timer; run it after a few weeks of new measurements, or after changing the coefficient.

## What it does not measure yet

The measurement leaves four things out, each for a stated reason.

- **Unfilled quantity.** A leg that was cancelled or expired unfilled has no fill price, so it is not in the table. What missing the trade cost, the opportunity cost, needs a later price to compare with and is left for a later stage.
- **The exchange's own acceptance time.** Latency ends at the broker's answer, which is when the engine recorded it, not at the exchange's timestamp, which not every broker reports reliably.
- **Paper fills.** A `paper_filled` parent never sent a leg, so it is not measured.
- **Quotes the feed did not carry.** An instrument the unified quote feed does not subscribe to has no ticks, so its legs are written with empty parts.

## What comes next

The last stage is to use what the first three produce.

1. The lowest-cost selector will compare brokers on brokerage plus expected latency cost in rupees, once a few weeks of ordinary trading show whether the brokers' latency figures really differ.
2. The estimate will help decide how to execute: how far a marketable limit may go through the book, when to slice an order instead of crossing at once, and how paper fills should be priced.
3. The impact coefficient will be fitted once orders larger than the visible book have been measured.
