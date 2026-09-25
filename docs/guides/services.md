# Running it as a service

Everything that runs does so as a systemd **user** unit: every script in `bin/<broker>/` and
`bin/unified/` that keeps running, each broker's morning login, the daily instrument and price jobs,
the REST API, and the check that keeps the database containers up. The scripts themselves are described in [Broker scripts](broker-scripts.md) and
[Unified scripts](unified-scripts.md); this page is about the units that run them.

## Layout

One folder per broker, one for the unified layer and one for the databases, each holding every unit that runs its part:

```text
services/
├── databases/
│   ├── databases.target
│   ├── databases.service              docker compose up -d --wait, run by the timer
│   └── databases.timer                every minute
├── <broker>/                          one each for the ten brokers
│   ├── <broker>.target
│   ├── <broker>-instruments@.service  one bin/<broker>/instruments/ script that keeps running
│   ├── <broker>-orders@.service       one bin/<broker>/orders/ script that keeps running
│   ├── <broker>-portfolio@.service    one bin/<broker>/portfolio/ script that keeps running
│   ├── <broker>-user@.service         one bin/<broker>/user/ script that keeps running
│   ├── <broker>-login.service         bin/<broker>/session/connect, run by the timer
│   ├── <broker>-login.timer           07:00 daily
│   └── <broker>-historical-prices.service   bin/<broker>/instruments/price_history, where the broker serves candles
└── unified/
    ├── unified.target
    ├── unified-instruments@.service   one bin/unified/instruments/ script that keeps running
    ├── unified-orders@.service        one bin/unified/orders/ script that keeps running
    ├── unified-portfolio@.service     one bin/unified/portfolio/ script that keeps running
    ├── unified-user@.service          one bin/unified/user/ script that keeps running
    ├── unified-brokers@.service       one bin/unified/brokers/ script that keeps running
    ├── unified-exchanges@.service     one bin/unified/exchanges/ script that keeps running
    ├── unified-mapping.service        every broker's instrument download, then bin/unified/instruments/map
    ├── unified-mapping.timer          07:45 daily
    ├── unified-prices.service         bin/unified/instruments/price_history daily
    ├── unified-prices.timer           08:30 Mon-Sat
    └── unified-rest-api.service       bin/rest-api
```

Every unit declares `PartOf=` its folder's target, so stopping or restarting `zerodha.target` stops or
restarts everything Zerodha runs. Groww, Kotak and Stoxkart have no `-historical-prices` unit, since none
of them serves candles. Every broker's `bin/<broker>/instruments/daily_feed` runs from `unified-mapping.service`
rather than from the broker's own folder.

Every `ExecStart` is `%h/Projects/unified_broker_interface/bin/...`, so the units expect the
repository at `~/Projects/unified_broker_interface`.

## Installing

Each target file carries its own install commands in its header comment. Install the databases first, because every other unit reads from them:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/databases/*
systemctl --user daemon-reload
systemctl --user enable --now databases.target databases.timer
```

`databases.service` runs `docker compose up -d --wait` against the project's `docker-compose.yml` every minute. It starts any of the Redis, MongoDB and TimescaleDB containers that is stopped or missing, leaves running ones alone, and fails unless all three report healthy. Docker already restarts a crashed container through `restart: unless-stopped`, so the timer is for the cases Docker leaves alone: a container stopped by hand, removed, or never created. To stop the databases on purpose, stop `databases.timer` first, or it starts them again within a minute. See [Data stores](../getting-started/data-stores.md#running-the-stores-with-docker).

For a broker - Zerodha here:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/zerodha/*
systemctl --user daemon-reload
systemctl --user enable --now zerodha.target zerodha-login.timer \
    zerodha-instruments@websocket_quotes.service zerodha-instruments@store_quotes_to_db.service \
    zerodha-orders@websocket_order_details.service zerodha-orders@store_orders_to_db.service \
    zerodha-orders@api_order_details.service zerodha-orders@api_trade_details.service \
    zerodha-portfolio@positions.service zerodha-portfolio@holdings.service zerodha-portfolio@funds.service \
    zerodha-user@details.service zerodha-historical-prices.service
```

And for the unified layer:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/unified/*
systemctl --user daemon-reload
systemctl --user enable --now unified.target unified-mapping.timer unified-prices.timer \
    unified-instruments@websocket_quotes.service unified-instruments@store_quotes_to_db.service \
    unified-orders@api_order_details.service unified-orders@api_trade_details.service \
    unified-orders@websocket_order_details.service unified-orders@store_orders_to_db.service \
    unified-portfolio@positions.service unified-portfolio@holdings.service \
    unified-portfolio@funds.service unified-portfolio@store_positions_to_db.service \
    unified-user@details.service unified-user@unified_details.service \
    unified-brokers@unified_details.service unified-exchanges@unified_details.service \
    unified-rest-api.service
```

The order engine is not in that list on purpose. `bin/unified/orders/order_engine` runs only when the
REST API is configured with `UNIFIED_BROKER_INTERFACE_API_ORDER_PLACEMENT=engine`, so it is enabled as a
separate step, under the same template as every other script in its folder:

```bash
systemctl --user enable --now unified-orders@order_engine.service
```

Run exactly one. The engine takes `unified:orders:engine:lock` before it does anything else and exits 1
if another process holds it, because two engines reading the same consumer group would place every order
twice. [The order engine](rest-api.md#the-order-engine) describes what it does.

`bin/unified/orders/virtual_book` keeps the synthetic limit order book: a queue estimate for every
`virtual_limit` order the engine is holding. It is needed only beside the engine, and only when
`virtual_limit` orders are used, so it is enabled as a separate step as well:

```bash
systemctl --user enable --now unified-orders@virtual_book.service
```

Without it a held order is still sent when the other side of the book reaches its price, but no
`missed_quantity` is recorded and a `paper: true` order never fills. Unlike the engine, more than one copy
does no harm beyond wasted work, because it only writes estimates and never places an order. See
[The synthetic limit order book](unified-scripts.md#the-synthetic-limit-order-book-virtual_book).

`systemctl --user link` symlinks the files, so editing a unit in `services/` takes effect after a
`daemon-reload` - and moving the repository breaks every installed unit.

The unified scripts read only what the broker scripts write to Redis, so a broker's data appears in
the unified keys only while that broker's target is running.

### What each broker enables

Every broker enables `instruments@websocket_quotes`, `instruments@store_quotes_to_db`,
`orders@store_orders_to_db`, `orders@api_order_details`, `orders@api_trade_details`,
`portfolio@positions`, `portfolio@holdings` and `portfolio@funds`, plus its login timer. The rest differ,
as the target files list them:

| Broker | `orders@websocket_order_details` | `portfolio@store_positions_to_db` | `user@details` | `-historical-prices` |
| --- | --- | --- | --- | --- |
| dhan | yes | - | yes | yes |
| flattrade | **no** | - | yes | yes |
| fyers | yes | yes | yes | yes |
| groww | yes | yes | yes | - |
| indmoney | yes | - | yes | yes |
| kotak | yes | yes | - | - |
| shoonya | yes | - | yes | yes |
| stoxkart | yes | - | yes | - |
| wisdom_capital | yes | yes | yes | yes |
| zerodha | yes | - | yes | yes |

`portfolio@store_positions_to_db` runs for the four brokers that stream positions over their order update
websocket. Kotak has no `user/details` script because it has no profile endpoint; `KotakAPI` writes the profile from
the login response instead, in whichever process logged in. Flattrade's order update feed is left out on
purpose: Flattrade permits one websocket per session and `flattrade-instruments@websocket_quotes` holds it, so enabling both
would knock one of them off. See [Known issues](../contributing/known-issues.md#broker-limits).
Stoxkart keeps one order socket per client, so `stoxkart-orders@websocket_order_details` and a Stoxkart website or app
logged in to the same account knock each other off; the script then waits five minutes before reclaiming
the socket. Stoxkart has no `portfolio@store_positions_to_db`, because it streams no position updates.

!!! warning "Linger is not optional"

    Without `loginctl enable-linger`, the user manager exits when you log out and takes every
    service with it. Check it with `loginctl show-user $USER | grep Linger`; it is `yes` on the
    production machine.

## The units

### The per-folder templates

A template per folder, whose instance name is the script inside it: `zerodha-instruments@websocket_quotes.service`
runs `bin/zerodha/instruments/websocket_quotes`, and `unified-user@details.service` runs
`bin/unified/user/details`. Each broker has four of these, one for `instruments/`, `orders/`, `portfolio/`
and `user/`, and the unified layer has six, adding `brokers/` and `exchanges/`; nothing in `session/` runs
as a long-lived service, since the login has its own oneshot unit and the logout is run by hand. The
polling scripts, the websocket
feeders, the combiners and the persisters all fit it, because each one looks after itself - a broker
script logs in by itself and logs in again when its token is refused, and a unified script reads only
Redis and the database and retries a store it cannot reach.

| Setting | Value | Why |
| --- | --- | --- |
| `Restart` | `always`, after 15 seconds | A script exits non-zero only when it cannot recover |
| `StartLimitIntervalSec` | `0` | Never give up restarting: a broker outage can outlast any start limit |
| `RestartPreventExitStatus` | `2` | A bad argument or configuration - nothing to subscribe to, say - which a restart cannot fix, so the unit is left failed and visible |
| `TimeoutStopSec` | 60 seconds | On SIGTERM a persister first writes and acknowledges the batch in hand |
| `Environment` | `PYTHONUNBUFFERED=1` | Python block-buffers stdout when it is not a terminal, and the journal would stay empty |

The broker templates are ordered after `network-online.target`; the unified one, which calls no broker,
is not. The four Fyers templates alone add an `ExecStartPre` that sleeps a random 0 to 30 seconds: Fyers
refuses more than a handful of requests a second per app, and eleven Fyers scripts each checking their
session at once when `fyers.target` starts was refused, and one script's login then spoiled another's
auth code.

### `<broker>-login.service`

A oneshot running `bin/<broker>/session/connect`, which checks the stored session, logs in only when it is
dead, and writes the outcome to `<broker>:session:status`. It has no `[Install]` section: the timer
starts it, or you do.

```bash
systemctl --user start zerodha-login          # log in now
journalctl --user -u zerodha-login
```

It is tried up to three times. The script exits non-zero when the login fails or the session it
produced does not answer an authenticated request, and `Restart=on-failure` runs it again after two
minutes; `StartLimitBurst=3` within `StartLimitIntervalSec=1h` counts the first attempt, so that is the
first try and two retries. `TimeoutStartSec` is 300 seconds, because Zerodha and Shoonya log in by driving
a headless Chrome and waiting on a TOTP - and for the same reason the unit deliberately has no
`PrivateTmp`, `ProtectHome` or `NoNewPrivileges`: Chrome needs a writable home and `/dev/shm`.

Nothing is restarted after a login. Every `bin/<broker>/` script reads the current token on each
connect and request, so a login made by any process is picked up by all of them; the morning login
only has to happen before the market opens.

### `<broker>-historical-prices.service`

`bin/<broker>/instruments/price_history`, working the broker's candle queue into `<broker>.price_history`. A
unit of its own rather than a `<broker>@historical_prices` instance, because it paces differently from
the feeds:

| Setting | Value | Why |
| --- | --- | --- |
| `ExecStartPre` | `bin/wait-for-redis` | Redis refuses every command while it reads its saved dataset back after a restart, and the worker's first login reads the stored token out of Redis |
| `Restart` | `always`, after 600 seconds | The worker exits 0 when the queue is drained or only backing off, so it starts again ten minutes later rather than at once |
| `RestartPreventExitStatus` | unset, unlike every other unit | Every exit is retried, exit 2 included: ten minutes is slow enough that a real misconfiguration reads as an obvious slow loop in the journal, and a first login that failed because a store was not ready yet gets another go |
| `TimeoutStartSec` | 420 seconds | Longer than the five minutes `bin/wait-for-redis` waits, so the wait decides when to give up rather than systemd |
| `TimeoutStopSec` | 120 seconds | Each window is committed with its progress in one transaction, so stopping costs at most the request in flight |
| `Nice`, `IOSchedulingClass`, `CPUWeight` | `10`, `idle`, `20` | A background backfill, at low priority |

The queue is not locked between workers, so run exactly one per broker. Seed newly listed
instruments after a new master with `bin/<broker>/instruments/price_history --seed-only`, and see how far it
has got with `bin/<broker>/instruments/price_history --status`. Fyers' unit carries the same random start
delay as its four templates, after the wait for Redis rather than before it, so the delay still spreads
the Fyers scripts apart once Redis lets them all go at once.

`bin/wait-for-redis` polls `INFO persistence` rather than `PING`, because `INFO` is one of the few
commands Redis answers while it is loading and its `loading` field is the server's own statement about
whether the dataset is in memory yet. It returns in about a quarter of a second when Redis is already
serving, logs each reason it is waiting once, and exits 1 after five minutes so the unit fails visibly
rather than hanging. It is a plain script, so it can be run by hand and put in front of any other unit
that reads Redis as it starts.

### `unified-mapping.service`

The daily instrument job: `bin/<broker>/instruments/daily_feed` for all ten brokers, Stoxkart included, then
`bin/unified/instruments/map`. Every download line is prefixed with `-`, so one broker's file not
arriving does not cost the others their mapping - `map` skips a broker with no rows stored
for the date - and the mapping's own exit status is the unit's. `TimeoutStartSec` is three hours; a
run is about three quarters of an hour. It runs at low priority, like the candle workers.

```bash
systemctl --user start unified-mapping      # run it now
journalctl --user -u unified-mapping
```

### `unified-prices.service`

`bin/unified/instruments/price_history daily`: `load`, `corrections`, `load` again, `factors --stale-days 14`
and `verify`, with a failed verify reported but not fatal. It is ordered after
`unified-mapping.service`, has a four hour `TimeoutStartSec` - the first factors run over every
instrument is thousands of Yahoo requests at about one a second - and runs at low priority. See
[Unified price history](unified-price-history.md).

```bash
systemctl --user start unified-prices           # run it now
bin/unified/instruments/price_history status
```

### `unified-rest-api.service`

`bin/rest-api`, which replaces itself with gunicorn, so systemd supervises gunicorn directly.
`Restart=always` after five seconds, with exit status 2 excluded so a crash loop is visible rather
than hidden behind fast restarts - order writes reach live broker accounts. `TimeoutStopSec` is 60
seconds, because gunicorn finishes the requests in flight on SIGTERM and a streamed
`/api/instruments/ticks` can take a while to end.

```bash
systemctl --user enable --now unified-rest-api.service
journalctl --user -u unified-rest-api -f
curl -s localhost:8080/api/
```

It answers from what the `unified-*@` scripts keep in Redis and from the unified tables, so it is useful
once `unified.target` is up, but it does not require it: a route whose document is missing answers 503
and names the key, rather than the service failing to start. The address, port and token lifetime come
from the environment; override them with a drop-in:

```ini
# systemctl --user edit unified-rest-api
[Service]
Environment=UNIFIED_BROKER_INTERFACE_API_PORT=8090
```

See [REST API](rest-api.md).

## The timers

| Timer | `OnCalendar` | Jitter | `Persistent` | Starts |
| --- | --- | --- | --- | --- |
| `<broker>-login.timer` | `*-*-* 07:00 Asia/Kolkata` | up to 30 minutes | `false` | `<broker>-login.service` |
| `unified-mapping.timer` | `*-*-* 07:45 Asia/Kolkata` | - | `true` | `unified-mapping.service` |
| `unified-prices.timer` | `Mon..Sat 08:30 Asia/Kolkata` | - | `true` | `unified-prices.service` |

The timezone is written into each schedule so it survives a change to the machine's timezone.

**07:45**, every day including weekends, comes after the logins because the brokers publish the day's masters overnight and the mapping has to
be in place before the 09:00 pre-open, when the feeders resolve against it. It is
`Persistent`: a snapshot missed can never be fetched later - the brokers publish only today's file -
so a machine that was off at 07:45 runs the job as soon as it starts.

**07:00**, every day including weekends, is before the instrument download and the pre-open, and
well clear of MCX's 23:30 close. `RandomizedDelaySec=1800` spreads ten logins, nine of them with a TOTP and two
of those through a headless Chrome, across 07:00 to 07:30 rather than firing them in the same second. A machine that was
off at 07:00 needs no catch-up, since the first script to find its token refused logs in then - hence
`Persistent=false`.

**08:30**, Monday to Saturday, comes after the night's candle downloads and the instrument job, and on
Saturday picks up Friday's last bars and the week's corporate actions. The instrument job can outlast
08:30, and `unified-prices.service` is ordered `After=unified-mapping.service`: a start queued while
that job is still running waits, as `start waiting` in `systemctl --user list-jobs`, and begins the moment
it finishes, so the history always loads against the day's mapping.

```bash
systemctl --user list-timers 'unified-*' '*-login.timer'
```

## Watching it

Every unit sets `SyslogIdentifier` to its own name - `zerodha-instruments-websocket_quotes`, `unified-persist_ticks`,
`zerodha-login`, `unified-mapping` - so the journal can be read by unit or by identifier:

```bash
journalctl --user -u zerodha-instruments@websocket_quotes -f
journalctl --user -u unified-instruments@store_quotes_to_db --since today
journalctl --user -u 'zerodha*' --since today              # everything Zerodha ran today
journalctl --user -t unified-prices --since today
systemctl --user list-units 'zerodha*' 'unified*'
systemctl --user status zerodha.target
```

After a reboot, `bin/check-services` checks every unit in one go and starts the ones that should be
running but are not. It finds the units from the `services/` folders, so it needs no list of its own:

```bash
bin/check-services                # check, and start what is down
bin/check-services --check-only   # report only
bin/check-services --all          # list every unit, not only the ones that needed attention
```

It starts targets, timers and every `Restart=always` service a target wants, including the candle
downloaders and the REST API. It never starts a login, instrument or price job, because a login
reaches a live broker account and at Zerodha cancels the token every running script holds; it only
reports those when they have failed. It also reports whether linger is on. It exits 0 when
everything is healthy, 1 when something still needs attention, and 2 for a bad argument or when the user's systemd manager cannot be reached.

The scripts record their own state in Redis as well - `<broker>:session:status` after every login,
`unified:prices:last_run` after every price run, `unified:mapping:meta` after every mapping - and a
persister's lag is on its stream's consumer group:

```bash
redis-cli GET zerodha:session:status
redis-cli XINFO GROUPS zerodha:quotes:stream
```

See [Redis keys](../architecture/redis-keys.md).
