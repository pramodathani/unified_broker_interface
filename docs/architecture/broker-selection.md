# Choosing a broker by cost

An order placed through `POST /api/orders/place` names an instrument, not a broker, so the system has to decide which of the ten accounts sends it. Two things pull on that decision. The brokers charge very different brokerage for the same order: an F&O order costs nothing at Flattrade and ₹20 at Zerodha. The brokers also limit how many order messages they accept per second, per minute, per hour and per day, and an order sent to a broker whose budget is used up is refused or delayed.

The `lowest_cost` selector, the default since 2026-09-29, weighs both. It sends each order to the broker that charges least for it, and keeps every broker inside its budgets. It replaced round robin, which gave the brokers turns in order and knew nothing about cost or about any limit longer than a second. Round robin and `fixed_priority` are still available through `UNIFIED_BROKER_INTERFACE_API_ORDER_BROKER_SELECTOR`, as described in [How the broker is chosen](../rest-api/orders.md#how-the-broker-is-chosen).

The diagram below shows F&O orders passing through the selector. Most go to the two free brokers, and a few spill to the ₹5 broker once the free brokers' minutes are full. The blue dots are the selector's two inputs: Redis counts read on every order, and the cost table read once a day.

<figure class="diagram">
--8<-- "docs/assets/diagrams/broker-selection.svg"
<figcaption>F&amp;O orders fill the free brokers first; the counts are read on every order, and the table once a day.</figcaption>
</figure>

## The cost table

Every number the selector uses comes from the PostgreSQL table `unified.broker_order_costs`. The selector's code names no broker, fee or limit, so changing a fee, adding a limit or adding a broker is a change to a row, not to code. The table below shows the rows it was seeded with.

| broker | orders_per_sec | orders_per_minute | orders_per_hour | orders_per_day | brokerage_for_delivery | brokerage_for_fno | brokerage_for_intraday |
|---|---|---|---|---|---|---|---|
| dhan | 9 | 480 | 7,000 | | 0 | 20 | 20 |
| flattrade | 10 | 180 | | | 0 | 0 | 0 |
| fyers | 8 | 180 | | 100,000 | 0 | 20 | 20 |
| groww | 9 | 240 | | | 20 | 20 | 20 |
| indmoney | 7 | 540 | | | 20 | 20 | 20 |
| kotak | 9 | 600 | | | 20 | 20 | 10 |
| shoonya | 8 | 540 | | | 0 | 5 | 5 |
| stoxkart | 6 | 420 | | | 0 | 20 | 20 |
| wisdom_capital | 8 | 540 | | | 0 | 0 | 0 |
| zerodha | 9 | 375 | | 4,500 | 0 | 20 | 20 |

The columns mean the following.

- **`broker`** is the name the code uses, such as `kotak` for Kotak Neo and `shoonya` for Shoonya (Finvasia).
- **The four `orders_per_*` columns** limit order messages, and a placement, a modification and a cancellation each count as one message. An empty cell (`NULL`) means the broker sets no limit for that window. A zero or a negative number is refused by the table's `CHECK` constraints when it is written.
- **The three `brokerage_for_*` columns** are the rupees charged for one order of each kind. They cannot be `NULL` or negative.

The table is created and seeded by `stock_brokers/instruments/mapping/utilities/sql/ddl/150_unified_broker_order_costs.sql`. That file runs with the rest of the unified schema, by `python -m stock_brokers.instruments.mapping.utilities.sql.apply_ddl` and before every daily mapping run. Its seed uses `ON CONFLICT (broker) DO NOTHING`, so running it again never overwrites a row that has been changed since.

`latency_cost_bps_intraday`, `latency_cost_bps_delivery` and `latency_cost_bps_fno` are how far, on average, the mid-price moved against an order while the broker handled it, in basis points, and `broker_answer_milliseconds` is the broker's median time to answer. `bin/unified/orders/latency_calibration` writes them and `latency_calibrated_at` every weekday night from the measured fills. **The selector does not read them yet**; [Measuring execution costs](execution-costs.md#the-latency-calibration) explains what they are for and why they wait.

### Changing a row or adding a broker

A change takes effect at the next 06:00 IST reload, or when the REST API and the order engine are next restarted. This statement adds a broker, or replaces every value of one that is already there:

```sql
INSERT INTO unified.broker_order_costs (
    broker,
    orders_per_sec,
    orders_per_minute,
    orders_per_hour,
    orders_per_day,
    brokerage_for_delivery,
    brokerage_for_fno,
    brokerage_for_intraday
)
VALUES ('new_broker', 10, 600, NULL, NULL, 0, 20, 20)
ON CONFLICT (broker) DO UPDATE SET
    orders_per_sec = EXCLUDED.orders_per_sec,
    orders_per_minute = EXCLUDED.orders_per_minute,
    orders_per_hour = EXCLUDED.orders_per_hour,
    orders_per_day = EXCLUDED.orders_per_day,
    brokerage_for_delivery = EXCLUDED.brokerage_for_delivery,
    brokerage_for_fno = EXCLUDED.brokerage_for_fno,
    brokerage_for_intraday = EXCLUDED.brokerage_for_intraday,
    updated_at = now();
```

A row only matters for a broker the API can place orders at, which needs the broker's `BrokerOrders` class as described in [Adding a broker](../project/adding-a-broker.md). A row for any other name is loaded and ignored. A broker the API can place orders at but that has no row is offered orders after every broker that has one, and a warning naming it is logged when the table loads.

## How an order's category is decided

The table prices three kinds of order, and the selector decides which one an order is from the instrument and the product. The table below lists the rule, checked from the top.

| The order | Category | Column used |
|---|---|---|
| A future or an option, in any segment and with any product | `fno` | `brokerage_for_fno` |
| A cash instrument with product `CNC` | `delivery` | `brokerage_for_delivery` |
| A cash instrument with any other product | `intraday` | `brokerage_for_intraday` |

## The ranking

Each broker in the rotation gets a sort key with five parts. The brokers are then listed in ascending order of that key, and each part only breaks the ties the part before it leaves.

1. **Blocked.** A broker whose per-minute, per-hour or per-day budget is used up goes after every broker whose budgets are not. For the per-day budget, "used up" means the entry limit, which is the cap less the share kept for exits by `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAP_EXIT_RESERVE`, because that is where the order engine starts refusing new orders. A blocked broker is still listed rather than dropped, so an order is never refused only because the selector's counts were a moment old.
2. **Fee.** The brokerage for the order's category.
3. **Versatility.** For each of the other two categories, the selector works out how much cheaper this broker is than the dearest broker in the rotation, and adds the two together. A lower number goes first. This spends the brokers that are cheap only for this kind of order before the brokers that other kinds of order need. Without it, a delivery order would happily use up a minute at Flattrade, which is free for delivery, and leave the next F&O order to pay ₹5 or ₹20.
4. **Pressure.** This is the fullest of the broker's windows, measured as a share of what that window allows. A per-second, per-minute or per-hour window allows its limit. A per-day window is paced: by a given moment in the NSE equity session (09:15 to 15:30 IST), it allows the share of the day that has passed plus a tenth of the cap, and never more than the whole cap. A lower pressure goes first, so orders are shared between equally cheap brokers in proportion to their limits, and a broker with a daily cap does not spend its day in the first hour.
5. **Place in the rotation**, so the same counts always give the same answer.

The ranking only decides the order in which brokers are asked. After it, each broker's own `place_skip_reason` still passes over any broker that cannot take this particular order, such as one whose market listing does not cover the instrument, exactly as it did under round robin.

### What today's table produces

The table below shows the ranking when nothing has been sent yet. The orderings are simply what the rows produce, and they change by themselves when a row changes.

| Category | Ranking with nothing sent yet |
|---|---|
| `fno` | flattrade, wisdom_capital (₹0) → shoonya (₹5) → groww, indmoney, kotak, dhan, fyers, stoxkart, zerodha (₹20) |
| `delivery` | dhan, fyers, stoxkart, zerodha (₹0, free for nothing else) → shoonya (₹0, but ₹5 elsewhere) → flattrade, wisdom_capital (₹0, and free elsewhere) → groww, indmoney, kotak (₹20) |
| `intraday` | flattrade, wisdom_capital (₹0) → shoonya (₹5) → kotak (₹10) → groww, indmoney, dhan, fyers, stoxkart, zerodha (₹20) |

Some capacity arithmetic follows from those rows. The two free F&O brokers take 180 + 540 = 720 orders a minute between them before Shoonya is used. The four brokers that are free only for delivery take 480 + 180 + 420 + 375 = 1,455 delivery orders a minute before Shoonya, Flattrade or Wisdom Capital are touched.

## Where the counts come from

The selector reads every broker's counts in one Redis command, queued on the pipeline that already reads the instrument, so it adds no round trip. The command is a Lua script that counts, for each broker, the messages in the rate budget's windows for the last second, minute and hour, and reads today's count from the daily order count. Times come from the Redis server's clock, the same clock the windows are written with.

The windows fill only when a message is actually sent. The order engine chooses a broker when an order arrives but sends it a moment later, from that broker's lane, so a burst of orders arriving together would all see the same counts and all go to one broker. The selector therefore also remembers, in the engine's memory, which brokers it chose in the last second, minute and hour, and uses the higher of that number and Redis's count. A `dry_run` placement is remembered too, although nothing is sent, so a long run of dry runs makes the selector spread orders a little more than it needs to.

## The limits are enforced as well as steered around

The selector only decides where an order goes first. A close or a bracket leg names its broker and never passes through the selector, so the limits are also enforced when each message is sent.

| Limit | Enforced by | Where the number comes from |
|---|---|---|
| Per second | The rate budget, `unified:orders:rate:<broker>` | `orders_per_sec`, or `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_PER_BROKER_PER_SECOND` for a broker with no row or an empty cell |
| Per minute | The rate budget, `unified:orders:rate:<broker>:minute` | `orders_per_minute`; no limit when empty |
| Per hour | The rate budget, `unified:orders:rate:<broker>:hour` | `orders_per_hour`; no limit when empty |
| Per day | The daily order count, `unified:orders:daily_count:<broker>` | `orders_per_day`, or `UNIFIED_BROKER_INTERFACE_API_ORDER_DAILY_CAPS` for a broker the table leaves empty |

All the windows of one message are checked and counted in one Lua step, so a message counts in every window or in none. A message that finds a window full waits up to `UNIFIED_BROKER_INTERFACE_API_ORDER_RATE_WAIT_SECONDS` for room and is refused after that, which for a full minute usually means refused. The daily count's rules are unchanged, and are described in [Daily order caps](../rest-api/orders.md#daily-order-caps).

## Loaded once a day, never while an order waits

The table is read into memory by [`BrokerCostTable`][unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table.BrokerCostTable], with one `SELECT` when a process starts and again every day at 06:00 IST, on a background thread. A reload builds a complete new set of rows and swaps it in with one assignment, so an order never waits on the database and never sees a half-loaded table. The selector, the rate budget and the daily order count in one process share the same table object, so they always agree on the day's numbers.

Building the objects reads nothing. The REST API loads the table in `api.py` once every blueprint is mounted, and the order engine loads it straight after building its placement code. The table below lists what happens when the read fails.

| When | What goes wrong | What happens |
|---|---|---|
| The order engine starts | PostgreSQL cannot be read | Exits with code 1, which systemd restarts |
| The order engine starts | The table is empty | Exits with code 2, which systemd does not restart |
| A gunicorn worker starts | Either | The worker fails to boot, so the API does not start |
| The 06:00 reload | Either | The previous day's rows stay in use, and the error is logged |

This makes PostgreSQL something the REST API and the order engine need at start-up, where before they needed only Redis to place orders.

## Checking that a broker can afford the order

Cost and rate budgets decide which broker is *preferred*. A broker is only *offered* the order if it also has the money for it. Before 2026-09-30 nothing checked this, so an order could go to the cheapest broker, be refused there for want of margin, and come back as a rejection even though another account could have taken it. Now the selector estimates the margin the order needs at each broker and passes over every broker whose free cash is short, in the same way it passes over a broker with no login. The reason goes into the answer's `skipped` list, for example `needs about 185,671.65 of margin but has 12,675.96 free`.

The check calls no broker. The brokers' own margin calculators take 75 to 100 ms each, a full round trip per order, so they are used once a day to *measure* the numbers the check uses, and never while an order waits. The check adds two commands to the Redis pipeline the engine already sends to read the instrument, so an order still costs the same number of round trips.

### What it compares

For each broker in the rotation, the selector works out:

1. **The exchange's margin**, estimated by [`MarginEstimate`][unified_broker_interface.utilities.broker_selection.utilities.margin_estimate.MarginEstimate] from the rates in `unified.margin_rates` and the prices in `unified:quotes:live`.
2. **Times the broker's surcharge**, from the `margin_multiplier_*` columns of `unified.broker_order_costs`, or 1.15 for a broker that has never been measured.
3. **Times a cushion** of 5%, so a small move in price between the check and the fill does not turn into a rejection.

It compares that with **the broker's free cash** from `unified:portfolio:funds`, less any margin already promised to orders this process sent there in the last moment. A broker whose funds are `stale`, `missing`, `unreadable` or more than five seconds old is passed over, because assuming money exists is the dangerous direction.

### The estimate for each kind of order

Each kind of order has its own rule. The table below also shows how close each rule came to the brokers' own calculators on 2026-09-30, for the same orders at the same prices.

| Order | Estimate | Estimate on 2026-09-30 | Brokers' answer |
|---|---|---|---|
| Delivery (`CNC`) buy | quantity × price | 1,017.70 for 1 INFY | 1,017.40 |
| Delivery sell | nothing; the broker checks holdings instead | 0 | |
| Intraday (`MIS`) | quantity × price × the segment's VaR rate (at least 20%) | 203.54 | 203.48 |
| Future, bought or sold | quantity × price × (SPAN + exposure) | 167,119.85 for 1 lot of NIFTY | 167,109.41 |
| Option bought | quantity × premium | 7,962.50 | 7,962.50 |
| Option sold | quantity × **underlying** price × the underlying's futures rate | 166,296.83 for the 22800 call | 161,608.53 |
| Commodity future | quantity × price × (SPAN + exposure) | 271,036.10 for 1 lot of crude oil | 271,072.50 |

A market order is valued at the last traded price. When an order has no price and its instrument has no quote, the margin cannot be worked out, and no broker is passed over for funds; the broker decides, as before.

`unified.margin_rates` holds the rates per segment, with optional rows per underlying. The segment-wide rows are deliberately high (index derivatives 15%, stock derivatives 40%, commodities 47%), because an estimate that is too high only passes over a broker that could have taken the order, while one that is too low sends an order that will be refused. NIFTY and crude oil have rows measured on 2026-09-30.

### Brokers' surcharges

Six of the nine brokers with a margin calculator charge the exchange's margin to within half a percent. Three charge noticeably more, and the surcharge is what the multiplier columns hold.

| Broker | F&O | Commodity | Intraday | Hedge benefit |
|---|---|---|---|---|
| Zerodha, Dhan, Groww, Kotak | 1.000 | 1.000 | 1.000 | Zerodha, Dhan and Groww yes; Kotak has no basket calculator |
| Fyers | 1.001 | 1.000 | 1.005 | **No**: its calculator priced an iron condor as four separate legs in either order |
| INDmoney | 1.005 | not measured | 1.013 | Not measured |
| Shoonya | 1.055 | 1.050 | 1.053 | Yes |
| Wisdom Capital | 1.100 | not measured | **1.375** | Yes |
| Flattrade | 1.111 | 1.110 | 1.101 | Yes |
| Stoxkart | not measured | not measured | not measured | Not measured; it has no margin calculator |

`bin/unified/orders/margin_calibration` re-measures these every trading morning by sending the same reference orders to each broker's calculator, and writes the ratios back. See [Scripts](../operations/scripts.md).

### Which money a broker has

Some brokers keep money for different markets apart. Zerodha and Fyers hold commodity money separately from equity money, and Groww and INDmoney split theirs by segment. The funds combiner writes each broker's own free cash and these separate `pools` into `unified:portfolio:funds`, and the check reads the pool that matches the order: `commodity` for a commodity order, `derivatives` and then `equity` for futures and options, and `equity` for shares. A broker with one pool offers its whole `available_balance`. On 2026-09-30 Zerodha's account had commodity trading switched off, so its commodity pool was 0 and a crude oil order passed it over.

### Strategies, and hedge benefit

A basket sends every leg to the broker its first leg chooses, because margin offsets exist only inside one account. The first leg therefore hands the whole list to the selector, and the check asks whether the broker can afford the whole strategy, not only its first order. A broker checks each order as it arrives, so the estimate is the **highest** requirement reached while the legs go out in the given order.

With `"hedge_benefit": true` in the basket's `synthetic` object, options and futures on one underlying with one expiry are priced as one position at the brokers whose `gives_hedge_benefit` is true:

```text
hedged margin = the most the legs can lose at expiry, leaving out premiums
              + exposure on every sold option and every future
              + the premium paid for every bought option
```

The most the legs can lose is found by [`OptionPayoff`][unified_broker_interface.utilities.broker_selection.utilities.option_payoff.OptionPayoff], which evaluates the payoff at an underlying price of zero and at every strike, where the lowest point must lie. If more calls and futures are sold than bought, the loss has no limit and the legs are added up instead. For the NIFTY iron condor of 2026-09-30 (23200 call and 22400 put bought, 23000 call and 22600 put sold, one lot each), the estimate and the brokers compare like this:

| | Margin |
|---|---|
| This estimate, bought legs first, hedge benefit | 75,786.75 |
| Shoonya, Groww, Dhan | 75,407 to 75,924 |
| Flattrade, Wisdom Capital (before their surcharges) | 79,724 and 82,847 |
| Zerodha, which also credits the premium received | 66,753 |
| This estimate without hedge benefit, or with the sold legs first | 333,829 to 336,305 |

Sending the sold legs first costs more than four times as much, because the broker sees two naked options before the protection arrives. The basket keeps the order it was given, so put the bought legs first.

### Orders sent in a burst

Funds are read every half second, so ten orders arriving together would all see the same balance. When a broker is chosen, [`FundsReservations`][unified_broker_interface.utilities.broker_selection.utilities.funds_reservations.FundsReservations] records the order's margin against it, and later orders see the balance less those reservations. A reservation is dropped once the broker's funds were read more than two seconds after it, because by then the balance shows the order, or the order was refused and never used the money. A dry run reserves nothing.

### When the check does nothing

The check is off, and queues nothing, in three cases:

| Case | Why |
|---|---|
| `UNIFIED_BROKER_INTERFACE_API_ORDER_FUNDS_CHECK=false` | To turn it off without a deploy |
| `unified.margin_rates` is empty or has not been loaded | A process loads it at start-up with the cost table; the offline suites never do, which keeps their recordings unchanged |
| The selector is `round_robin` or `fixed_priority` | Only the lowest-cost selector checks funds |

Orders that name their broker, such as the closing orders of [flatten](../rest-api/flatten.md) and every leg after a strategy's first, are never checked: an exit frees margin, and a later leg has to go where the first one went.

## Other ways this could have been done

Five approaches were considered when this selector was designed. The one built is the third, and the first two are special cases of it.

| # | Approach | How it decides | Verdict |
|---|---|---|---|
| 1 | Cheapest first, ties by headroom | The cheapest broker for the category; among equal fees, the one with the most room left | Greedy: a delivery order can use up the room at a broker an F&O order needed to be free |
| 2 | Approach 1, plus versatility | Among equal fees, the broker the other categories need least goes first | Fixes the waste in approach 1 at no cost |
| 3 | Approach 2, plus pacing | Per-day budgets are measured against a share that grows through the session | **Built** |
| 4 | A soft score: fee plus a penalty for fullness | Pays a dearer broker early to keep room at a cheap one | Rejected, because it spends real brokerage to insure against a burst that may never come |
| 5 | Plan a whole day at once as an optimisation problem | Solves for the cheapest assignment of a day's orders | Rejected for live orders, because it needs a forecast of the day and takes too long per order; it could serve as an offline benchmark |

## Under the hood

The table below lists where each piece lives.

| Piece | Class or file |
|---|---|
| The ranking | [`LowestCostSelector`][unified_broker_interface.utilities.broker_selection.lowest_cost.LowestCostSelector] |
| The table in memory and its daily reload | [`BrokerCostTable`][unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table.BrokerCostTable] |
| One broker's row | [`BrokerCosts`][unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table.BrokerCosts] |
| The per-second, per-minute and per-hour windows | [`RateBudget`][unified_broker_interface.utilities.order_engine.utilities.rate_budget.RateBudget] |
| The per-day count | [`DailyOrderCount`][unified_broker_interface.utilities.order_engine.utilities.daily_order_count.DailyOrderCount] |
| The table's definition and seed | `stock_brokers/instruments/mapping/utilities/sql/ddl/150_unified_broker_order_costs.sql` |
| The funds check | [`FundsCheck`][unified_broker_interface.utilities.broker_selection.utilities.funds_check.FundsCheck] |
| The margin estimate | [`MarginEstimate`][unified_broker_interface.utilities.broker_selection.utilities.margin_estimate.MarginEstimate], [`OptionPayoff`][unified_broker_interface.utilities.broker_selection.utilities.option_payoff.OptionPayoff] and [`PricedLeg`][unified_broker_interface.utilities.broker_selection.utilities.priced_leg.PricedLeg] |
| A strategy's legs | [`OrderLegs`][unified_broker_interface.utilities.broker_selection.utilities.order_legs.OrderLegs] |
| Margin promised to orders just sent | [`FundsReservations`][unified_broker_interface.utilities.broker_selection.utilities.funds_reservations.FundsReservations] |
| The margin rates in memory | [`MarginRateTable`][unified_broker_interface.utilities.broker_selection.utilities.margin_rate_table.MarginRateTable] |
| The margin rates' definition and seed | `stock_brokers/instruments/mapping/utilities/sql/ddl/160_unified_margin_rates.sql` |
| Offline checks | `python -m test_runs.broker_selection` and `python -m test_runs.funds_check` |
