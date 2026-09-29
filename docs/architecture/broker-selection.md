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
| Offline checks | `python -m test_runs.broker_selection` |
