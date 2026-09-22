"""
Establishing a broker session, once, safely, from however many processes want one.

Logging in is a side effect of constructing a broker's API class, which probes an authenticated
endpoint and only runs the real login flow when that probe fails. A process that only reads
`last_login` from MongoDB refreshes nothing - one that has been up across the overnight token
expiry will keep sending requests against a dead session unless something constructs the API object.

That is what this module is for. The historical candle downloaders call it through `BrokerCandles`
when they log in, and IND Money's instrument ingester calls it when no usable token is stored. Two
things make it more than a one line helper.

**Only one login at a time.** Kite issues one access token per session and a second login
invalidates the first. Two processes starting together and both logging in would race, and the
loser would come up holding a token that had already been replaced. A Redis lock makes one of
them do the work while the other waits for the result.

**A floor on how often a login may be attempted.** Several brokers log in by driving a headless
Chrome and consuming a TOTP. Under `Restart=always`, a broker outage would otherwise mean a full
Selenium login every time the process restarted - a few times a minute, indefinitely, which is
how an account gets locked. The rate limiter bounds that regardless of how often the service is
restarted, because it lives in Redis rather than in the process.
"""

import os
import time
from datetime import datetime

from utilities.configurations import get_cache, get_mongo_db, get_logger

# How long the login lock is held before Redis expires it. Longer than a Selenium login with a
# TOTP wait, so a slow login is not overtaken; short enough that a process killed mid-login does
# not block the next attempt for long.
LOCK_TIMEOUT_SECONDS = 300

# Floor on the interval between login attempts for one broker, however many processes ask.
MIN_LOGIN_INTERVAL_SECONDS = int(os.getenv("UNIFIED_BROKER_INTERFACE_LOGIN_MIN_INTERVAL", "300"))

# How long to wait for another process's login before giving up.
WAIT_FOR_OTHER_SECONDS = 300

def _lock_key(broker_name):
    """
    Redis key held while one process logs a broker in.

    - `broker_name` is the name of the broker.
    """
    return f"ubi:login:{broker_name}"

def _attempt_key(broker_name):
    """
    Redis key recording when a broker was last sent through its login flow.

    - `broker_name` is the name of the broker.
    """
    return f"ubi:login-attempt:{broker_name}"

def _success_key(broker_name):
    """
    Redis key recording when a broker's session was last confirmed working.

    Distinct from the attempt key because the usual outcome of `ensure_session` is that the
    stored token was already valid and only a probe happened, which changes nothing in MongoDB.
    Without a separate record there is no way to tell that from an attempt that failed.

    - `broker_name` is the name of the broker.
    """
    return f"ubi:login-ok:{broker_name}"

def api_class_for(broker_name):
    """
    The API class whose construction logs a broker in.

    Imported lazily and one at a time: several of these modules import Selenium at module level,
    and a process that only needs Zerodha should not pay for the other nine.

    - `broker_name` is the name of the broker.
    """
    import importlib

    modules = {
        "zerodha": ("stock_brokers.api.zerodha", "ZerodhaAPI"),
        "dhan": ("stock_brokers.api.dhan", "DhanAPI"),
        "flattrade": ("stock_brokers.api.flattrade", "FlattradeAPI"),
        "shoonya": ("stock_brokers.api.shoonya", "ShoonyaAPI"),
        "fyers": ("stock_brokers.api.fyers", "FyersAPI"),
        "groww": ("stock_brokers.api.groww", "GrowwAPI"),
        "kotak": ("stock_brokers.api.kotak", "KotakAPI"),
        "indmoney": ("stock_brokers.api.indmoney", "INDMoneyAPI"),
        "wisdom_capital": ("stock_brokers.api.wisdom_capital", "WisdomCapitalAPI"),
        "stoxkart": ("stock_brokers.api.stoxkart", "StoxkartAPI"),
    }
    if broker_name not in modules:
        raise ValueError(f"No API class known for broker {broker_name}. "
                         f"Known: {', '.join(sorted(modules))}")
    module_name, class_name = modules[broker_name]
    return getattr(importlib.import_module(module_name), class_name)

BROKERS_WITH_API = ("zerodha", "dhan", "flattrade", "shoonya", "fyers",
                    "groww", "kotak", "indmoney", "wisdom_capital", "stoxkart")

def stored_login(broker_name):
    """
    A broker's `last_login` document, or an empty dictionary.

    - `broker_name` is the name of the broker.
    """
    return get_mongo_db()['last_login'].find_one({'broker_name': broker_name}, {'_id': 0}) or {}

def _login_timestamp(document):
    """
    The moment a stored login was made, as an epoch, or None when it cannot be read.

    - `document` is a `last_login` document.
    """
    raw = (document or {}).get('last_login')
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").timestamp()
    except (TypeError, ValueError):
        return None

def _clear_dead_holder(broker_name, cache, logger):
    """
    Release the login lock if the process holding it no longer exists.

    The lock has an expiry, so a crashed holder always clears eventually - but eventually is up
    to five minutes, and this is reached on the ordinary path of restarting a service while it is
    inside `ensure_session`, before its signal handlers are installed. Waiting out the expiry
    every time would make a restart look like a hang.

    The lock holds the holder's process id, and everything that takes it runs on this machine, so
    a liveness check is a signal 0. Returns whether the lock was cleared.

    - `broker_name` is the name of the broker.
    - `cache` is the Redis client.
    - `logger` is where the release is reported.
    """
    holder = cache.get(_lock_key(broker_name))
    if not holder:
        return False

    try:
        pid = int(holder)
    except (TypeError, ValueError):
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.warning(f"The process that held the {broker_name} login lock (pid {pid}) is gone. "
                       f"Releasing it.")
        # Only delete if it is still the same holder, so a lock taken between the read and here
        # is not stolen from a live process.
        if cache.get(_lock_key(broker_name)) == holder:
            cache.delete(_lock_key(broker_name))
            return True
    except PermissionError:
        # The pid exists and belongs to somebody else, so it is alive as far as this matters.
        return False
    return False

class SessionException(Exception):
    """Raised when a broker session could not be established."""

def ensure_session(broker_name, force=False, logger=None):
    """
    Make sure a usable session exists for a broker, logging in if it does not.

    Constructing the broker's API class is what does the work: it probes an authenticated
    endpoint first, so the common case where the stored token is still good costs one HTTP
    request rather than a login.

    Returns the `last_login` document in force after the call.

    - `broker_name` is the name of the broker.
    - `force` skips the rate limiter, for a deliberate manual re-login.
    - `logger` is where progress is reported. A named logger is made when not supplied.
    """
    logger = logger or get_logger(f"{broker_name}.session")
    cache = get_cache()
    started_at = time.time()

    acquired = cache.set(_lock_key(broker_name), str(os.getpid()),
                         nx=True, ex=LOCK_TIMEOUT_SECONDS)

    if not acquired and _clear_dead_holder(broker_name, cache, logger):
        acquired = cache.set(_lock_key(broker_name), str(os.getpid()),
                             nx=True, ex=LOCK_TIMEOUT_SECONDS)

    if not acquired:
        logger.info(f"Another process is logging {broker_name} in. Waiting for it.")
        return _wait_for_other_process(broker_name, cache, started_at, logger)

    try:
        last_attempt = float(cache.get(_attempt_key(broker_name)) or 0)
        last_success = float(cache.get(_success_key(broker_name)) or 0)
        document = stored_login(broker_name)
        token = document.get('access_token')
        has_token = bool(token) and token != 'None'

        # A session confirmed working within the last interval is simply used. The confirmation
        # has to be recorded separately from the login itself, because the usual outcome is that
        # the stored token was already good and the API class only probed it - which writes
        # nothing to last_login. Comparing against the stored login time instead would treat a
        # perfectly valid token issued this morning as stale.
        #
        # This is the ordinary path: the login unit runs, then the services that need the session
        # start behind it and must not queue up behind a rate limiter meant for failed logins.
        if has_token and not force and last_success:
            age = time.time() - last_success
            if age < MIN_LOGIN_INTERVAL_SECONDS:
                logger.info(f"{broker_name} session was confirmed {age:.0f}s ago. Using it.")
                return document

        # Throttle only a genuine retry: an attempt that was made recently and did not end in a
        # confirmed session. Without this, a broker outage plus Restart=always would mean a full
        # Selenium login every eighty seconds, which is how an account gets locked.
        if last_attempt and not force and last_success < last_attempt:
            age = time.time() - last_attempt
            if age < MIN_LOGIN_INTERVAL_SECONDS:
                wait = MIN_LOGIN_INTERVAL_SECONDS - age
                logger.warning(
                    f"The last {broker_name} login attempt was {age:.0f}s ago and did not "
                    f"produce a working session. Waiting {wait:.0f}s before trying again.")
                time.sleep(wait)

        cache.set(_attempt_key(broker_name), str(time.time()))
        logger.info(f"Establishing a {broker_name} session.")
        api_class_for(broker_name)()
        cache.set(_success_key(broker_name), str(time.time()))
    except Exception as exception:
        raise SessionException(
            f"Could not establish a {broker_name} session: "
            f"{type(exception).__name__}: {exception}") from exception
    finally:
        cache.delete(_lock_key(broker_name))

    document = stored_login(broker_name)
    if not document.get('access_token') or document.get('access_token') == 'None':
        raise SessionException(
            f"{broker_name} login completed but stored no usable access token.")
    logger.info(f"{broker_name} session ready, logged in at {document.get('last_login')}.")
    return document

def _wait_for_other_process(broker_name, cache, started_at, logger):
    """
    Wait for whichever process holds the lock to finish, then use its result.

    Succeeds as soon as the stored login is newer than this call began, or as soon as the lock is
    gone and a usable token is present - the second case covers a login that was already valid
    and so wrote nothing new.

    - `broker_name` is the name of the broker.
    - `cache` is the Redis client.
    - `started_at` is the epoch at which this call began.
    - `logger` is where progress is reported.
    """
    deadline = started_at + WAIT_FOR_OTHER_SECONDS
    while time.time() < deadline:
        time.sleep(2)
        document = stored_login(broker_name)
        timestamp = _login_timestamp(document)
        if timestamp and timestamp >= started_at:
            logger.info(f"{broker_name} logged in by another process.")
            return document
        if not cache.exists(_lock_key(broker_name)):
            token = document.get('access_token')
            if token and token != 'None':
                logger.info(f"{broker_name} session already in place.")
                return document
            raise SessionException(
                f"The process logging {broker_name} in finished without storing a token.")
    raise SessionException(
        f"Timed out after {WAIT_FOR_OTHER_SECONDS}s waiting for another process to log "
        f"{broker_name} in.")
