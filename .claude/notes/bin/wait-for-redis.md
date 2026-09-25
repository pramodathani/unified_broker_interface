# bin/wait-for-redis

## Why this script exists at all

After the reboots of 2026-09-18 and 2026-09-22 all seven `<broker>-historical-prices.service` units
were dead. Each had started while Redis was still reading its saved dataset back from disk, which is
the one state where Redis answers ordinary commands with `BusyLoadingError` rather than serving them.
The worker's first act is to log in, the login reads the stored token out of Redis, and the refusal
was reported as `Could not log in to <Broker>: BusyLoadingError: Redis is loading the dataset in
memory`, which the script treats as a failed first login and reports with exit 2. The units carried
`RestartPreventExitStatus=2`, so systemd left all seven failed and they stayed down until someone ran
`bin/check-services`.

The entry in `docs/contributing/known-issues.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/known-issues.md`) named two possible fixes: treat `BusyLoadingError` as
a temporary error inside the login path, or order the units after Redis. The user chose the second,
and asked for it as an `ExecStartPre`. That entry has been moved to `docs/contributing/pitfalls.md` (removed in the documentation rebuild; read it with `git show b884d54:docs/contributing/pitfalls.md`),
since the bug is now fixed and the page records exactly this kind of failure.

## Why `INFO persistence` rather than `PING`

The obvious readiness test is a ping, but a ping conflates two different answers. Redis allows only a
small set of commands while it is loading, and whether `PING` is one of them has changed between
versions, so a ping either raises `BusyLoadingError`, which is indistinguishable from any other error,
or succeeds while the server still cannot serve a `GET`. `INFO` is answered throughout loading
precisely so that a client can ask about it, and its `loading` field is the server's own statement
about whether the dataset is in memory. `async_loading` is checked as well; it is the replica case,
which this deployment does not use today, and reading it costs nothing.

A failure to connect at all, which is what happens when the container has not started yet, arrives as
a `redis.exceptions.RedisError` from the same call, so one test covers both "Redis is not there" and
"Redis is there but not ready". The two are told apart in the log rather than in the code.

## Why a timeout of five minutes, and what happens after it

The script gives up after five minutes and exits 1, rather than waiting forever, so that a Redis that
never arrives shows as a failed unit in `systemctl --user --failed` instead of a unit stuck in
`activating` where nothing is obviously wrong. `TimeoutStartSec=420` in the units is deliberately
longer than the script's own five minutes, so the script decides when to give up and its log line says
why; if systemd's timer fired first the journal would only show that the pre-start step was killed.
Giving up is not final, because the units now restart on every exit, so a failed wait is retried ten
minutes later.

## Why the exit-2 guard was dropped from the units at the same time

The wait removes the usual cause of exit 2 but not the exit code itself: a broker that refuses the
stored token and then refuses the login still exits 2, and so does a bad argument. The user asked for
the candle workers to restart whenever they die, so `RestartPreventExitStatus=2` was removed from all
seven units. `RestartSec=600` already governs the pace, so the worst case of a genuine
misconfiguration is one start every ten minutes, which reads as an obvious slow loop in the journal
rather than a hot restart loop. Every other unit in the project keeps the guard.

## Why it sits at the top of `bin/` rather than beside the broker scripts

It reaches no broker and belongs to no broker, and it is useful by hand when a store has just been
restarted. It follows the top-level convention in every other respect: extensionless, executable, and
re-executing itself under the virtual environment through `run_under_venv`, which is what lets systemd
run it with no environment of its own.
