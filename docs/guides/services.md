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
│   ├── <broker>@.service              one bin/<broker>/ script that keeps running
│   ├── <broker>-login.service         bin/<broker>/login, run by the timer
│   ├── <broker>-login.timer           08:15 Mon-Fri
│   └── <broker>-historical-prices.service   bin/<broker>/historical_prices, where the broker serves candles
└── unified/
    ├── unified.target
    ├── unified@.service               one bin/unified/ script that keeps running
    ├── unified-instruments.service    every broker's instrument download, then bin/unified/map_instruments
    ├── unified-instruments.timer      07:45 Mon-Fri
    ├── unified-prices.service         bin/unified/historical_prices daily
    ├── unified-prices.timer           08:30 Mon-Sat
    └── unified-rest-api.service       bin/rest-api
```

Every unit declares `PartOf=` its folder's target, so stopping or restarting `zerodha.target` stops or
restarts everything Zerodha runs. Groww, Kotak and Stoxkart have no `-historical-prices` unit, since none
of them serves candles. Every broker's `bin/<broker>/instruments` runs from `unified-instruments.service`
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
    zerodha@quotes.service zerodha@order_updates.service zerodha@persist_ticks.service zerodha@persist_orders.service zerodha@orders.service zerodha@trades.service zerodha@positions.service zerodha@holdings.service zerodha@funds.service zerodha@user-profile.service zerodha-historical-prices.service
```

And for the unified layer:

```bash
systemctl --user link ~/Projects/unified_broker_interface/services/unified/*
systemctl --user daemon-reload
systemctl --user enable --now unified.target unified-instruments.timer unified-prices.timer \
    unified@quotes.service unified@order_updates.service unified@orders.service unified@trades.service unified@positions.service unified@holdings.service unified@funds.service unified@user-profile.service unified@details.service unified-rest-api.service unified@persist_ticks.service unified@persist_orders.service unified@persist_positions.service
```

`systemctl --user link` symlinks the files, so editing a unit in `services/` takes effect after a
`daemon-reload` - and moving the repository breaks every installed unit.

The unified scripts read only what the broker scripts write to Redis, so a broker's data appears in
the unified keys only while that broker's target is running.

### What each broker enables

Every broker enables `quotes`, `persist_ticks`, `orders`, `trades`, `positions`, `holdings` and `funds`
as `<broker>@` instances, plus its login timer, and every broker also enables `persist_orders`. The rest
differ, as the target files list them:

| Broker | `@order_updates` | `@persist_positions` | `@user-profile` | `-historical-prices` |
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

`persist_positions` runs for the four brokers that stream positions over their order update
websocket. Kotak has no `user-profile` script because it has no profile endpoint; `bin/kotak/login`
writes the profile from the login response instead. Flattrade's `order_updates` is left out on
purpose: Flattrade permits one websocket per session and `flattrade@quotes` holds it, so enabling both
would knock one of them off. See [Known issues](../contributing/known-issues.md#broker-limits).
Stoxkart keeps one order socket per client, so `stoxkart@order_updates` and a Stoxkart website or app
logged in to the same account knock each other off; the script then waits five minutes before reclaiming
the socket. Stoxkart has no `persist_positions`, because it streams no position updates.

!!! warning "Linger is not optional"

    Without `loginctl enable-linger`, the user manager exits when you log out and takes every
    service with it. Check it with `loginctl show-user $USER | grep Linger`; it is `yes` on the
    production machine.

## The units

### `<broker>@.service` and `unified@.service`

A template whose instance name is the script: `zerodha@quotes.service` runs `bin/zerodha/quotes`,
`unified@user-profile.service` runs `bin/unified/user-profile`. The polling scripts, the websocket
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

The broker template is ordered after `network-online.target`; the unified one, which calls no broker,
is not. `fyers@.service` alone adds an `ExecStartPre` that sleeps a random 0 to 30 seconds: Fyers
refuses more than a handful of requests a second per app, and eleven Fyers scripts each checking their
session at once when `fyers.target` starts was refused, and one script's login then spoiled another's
auth code.

### `<broker>-login.service`

A oneshot running `bin/<broker>/login`, which checks the stored session, logs in only when it is
dead, and writes the outcome to `<broker>:session:status`. It has no `[Install]` section: the timer
starts it, or you do.

```bash
systemctl --user start zerodha-login          # log in now
journalctl --user -u zerodha-login
```

It is tried up to three times. The script exits non-zero when the login fails or the session it
produced does not answer an authenticated request, and `Restart=on-failure` runs it again after two
minutes; `StartLimitBurst=3` within `StartLimitIntervalSec=1h` counts the first attempt, so that is the
first try and two retries. `TimeoutStartSec` is 300 seconds, because several brokers log in by driving
a headless Chrome and waiting on a TOTP - and for the same reason the unit deliberately has no
`PrivateTmp`, `ProtectHome` or `NoNewPrivileges`: Chrome needs a writable home and `/dev/shm`.

Nothing is restarted after a login. Every `bin/<broker>/` script reads the current token on each
connect and request, so a login made by any process is picked up by all of them; the morning login
only has to happen before the market opens.

### `<broker>-historical-prices.service`

`bin/<broker>/historical_prices`, working the broker's candle queue into `<broker>.price_history`. A
unit of its own rather than a `<broker>@historical_prices` instance, because it paces differently from
the feeds:

| Setting | Value | Why |
| --- | --- | --- |
| `Restart` | `always`, after 600 seconds | The worker exits 0 when the queue is drained or only backing off, so it starts again ten minutes later rather than at once |
| `RestartPreventExitStatus` | `2` | A failed first login or a bad argument; the morning login timer is the remedy, not a restart loop |
| `TimeoutStopSec` | 120 seconds | Each window is committed with its progress in one transaction, so stopping costs at most the request in flight |
| `Nice`, `IOSchedulingClass`, `CPUWeight` | `10`, `idle`, `20` | A background backfill, at low priority |

The queue is not locked between workers, so run exactly one per broker. Seed newly listed
instruments after a new master with `bin/<broker>/historical_prices --seed-only`, and see how far it
has got with `bin/<broker>/historical_prices --status`. Fyers' unit carries the same random start
delay as `fyers@.service`.

### `unified-instruments.service`

The daily instrument job: `bin/<broker>/instruments` for all ten brokers, Stoxkart included, then
`bin/unified/map_instruments`. Every download line is prefixed with `-`, so one broker's file not
arriving does not cost the others their mapping - `map_instruments` skips a broker with no rows stored
for the date - and the mapping's own exit status is the unit's. `TimeoutStartSec` is three hours; a
run is about three quarters of an hour. It runs at low priority, like the candle workers.

```bash
systemctl --user start unified-instruments      # run it now
journalctl --user -u unified-instruments
```

### `unified-prices.service`

`bin/unified/historical_prices daily`: `load`, `corrections`, `load` again, `factors --stale-days 14`
and `verify`, with a failed verify reported but not fatal. It is ordered after
`unified-instruments.service`, has a four hour `TimeoutStartSec` - the first factors run over every
instrument is thousands of Yahoo requests at about one a second - and runs at low priority. See
[Unified price history](unified-price-history.md).

```bash
systemctl --user start unified-prices           # run it now
bin/unified/historical_prices status
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

It answers from what the `unified@` scripts keep in Redis and from the unified tables, so it is useful
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
| `unified-instruments.timer` | `Mon..Fri 07:45 Asia/Kolkata` | - | `true` | `unified-instruments.service` |
| `<broker>-login.timer` | `Mon..Fri 08:15 Asia/Kolkata` | up to 30 minutes | `false` | `<broker>-login.service` |
| `unified-prices.timer` | `Mon..Sat 08:30 Asia/Kolkata` | - | `true` | `unified-prices.service` |

The timezone is written into each schedule so it survives a change to the machine's timezone.

**07:45** comes first because the brokers publish the day's masters overnight and the mapping has to
be in place before the logins and the 09:00 pre-open, when the feeders resolve against it. It is
`Persistent`: a snapshot missed can never be fetched later - the brokers publish only today's file -
so a machine that was off at 07:45 runs the job as soon as it starts.

**08:15** is after the overnight token expiry and the instrument download, before the pre-open, and
well clear of MCX's 23:30 close. `RandomizedDelaySec=1800` spreads ten logins, most of them a headless
Chrome and a TOTP, across 08:15 to 08:45 rather than firing them in the same second. A machine that was
off at 08:15 needs no catch-up, since the first script to find its token refused logs in then - hence
`Persistent=false`.

**08:30**, Monday to Saturday, comes after the night's candle downloads and the instrument job, and on
Saturday picks up Friday's last bars and the week's corporate actions. The instrument job can outlast
08:30, and `unified-prices.service` is ordered `After=unified-instruments.service`: a start queued while
that job is still running waits, as `start waiting` in `systemctl --user list-jobs`, and begins the moment
it finishes, so the history always loads against the day's mapping.

```bash
systemctl --user list-timers 'unified-*' '*-login.timer'
```

## Watching it

Every unit sets `SyslogIdentifier` to its own name - `zerodha-quotes`, `unified-persist_ticks`,
`zerodha-login`, `unified-instruments` - so the journal can be read by unit or by identifier:

```bash
journalctl --user -u zerodha@quotes -f
journalctl --user -u unified@persist_ticks --since today
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
everything is healthy and 1 when something still needs attention.

The scripts record their own state in Redis as well - `<broker>:session:status` after every login,
`unified:prices:last_run` after every price run, `unified:mapping:meta` after every mapping - and a
persister's lag is on its stream's consumer group:

```bash
redis-cli GET zerodha:session:status
redis-cli XINFO GROUPS zerodha:quotes:stream
```

See [Redis keys](../architecture/redis-keys.md).
