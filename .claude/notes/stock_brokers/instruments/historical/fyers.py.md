# Notes on `stock_brokers/instruments/historical/fyers.py`

## The request rate

Fyers documents no separate rate for the history endpoint. The original setting of 3 requests a second carried a comment calling it "a conservative figure rather than a published one", to be raised only after measuring.

Every Fyers request counts toward the app's documented 200 a minute and 100,000 a day, across every endpoint, and the history download shares them with the pollers and, until 2026-09-30, the order connection warmers. At 3 a second the history download alone was 180 a minute, and with the pollers (about 32) and the warmers (about 30) the total was about 240. The first Cloudflare ban of this machine's address came on 2026-09-27, three hours after warming every pooled connection began. On 2026-09-30 the rate was lowered to 2 a second (120 a minute) and Fyers was left out of `UNIFIED_BROKER_INTERFACE_API_ORDER_WARM_BROKERS`, bringing the total to about 150 a minute.

## The daily cap

`REQUESTS_PER_DAY = 45000` leaves room for the pollers, which run around the clock and use about 46,000 requests a day: the order book and positions every 5 seconds (17,280 each), trades every 15 (5,760), funds every 30 (2,880), holdings and the profile every 60 (1,440 each). 45,000 at 2 a second is about six and a quarter hours of downloading.

The cap is counted in Redis (`fyers:price_history:requests:<date>`) by `RateLimiter`, because the downloader exits when the budget is spent and systemd starts it again ten minutes later; a count kept in the process would start again at zero each time.

## Trading hours

At the user's request on 2026-09-30, the download does not run from 09:00 to 23:55 India time, Monday to Friday: from the equity pre-open to the latest close of MCX's evening session (23:55 while the United States is on standard time). The pause happens in `claim`, before a series is claimed, so no series is held while waiting, and it waits on the run's stop event so `systemctl stop` ends it at once. Exchange holidays are treated as trading days, which only costs a day's download. With the pause, the download has about nine hours each weekday night, which the 45,000 cap uses about six and a quarter of.

## A larger cap at weekends

At the user's request on 2026-09-30 the download runs all day at the weekend, with no trading-hours pause, and its cap there is `WEEKEND_REQUESTS_PER_DAY = 100000` rather than 45,000 (`daily_cap`). The user first asked for no weekend cap, then settled on 100,000. The user was told that with the pollers' roughly 46,000 a weekend day then comes to about 146,000 requests, above the 100,000 a day Fyers documents, while staying under 200 a minute (about 152). At 2 a second, 100,000 requests take about 13.9 hours. If Fyers starts refusing at weekends, this is the first thing to revisit.
