"""
Each broker's limits on how many orders may be sent to it, kept in Redis so every worker counts against the same
budget.

The windows are the brokers' published order limits: per second, per minute and per day. A window is a fixed
bucket - one Redis counter per window per bucket, expiring with it. A write takes a slot in every window before it
is sent; when any window is full, the slots are given back and the write is refused with how long to wait, rather
than holding a request thread until the window turns over. The router peeks at the same counters, without taking a
slot, to leave out a broker that is at its limit.
"""

import math
import time

# Per broker, the order-write limits as (window in seconds, most orders in it).
ORDER_WRITE_LIMITS = {
    "zerodha": [(1, 10), (60, 400), (86400, 5000)],
    "dhan": [(1, 10), (60, 250), (86400, 7000)],
    "groww": [(1, 10), (60, 250)],
    "indmoney": [(1, 10)],
    "kotak": [(1, 10)],
    "flattrade": [(1, 10)],
    "shoonya": [(1, 20), (60, 200)],
    "fyers": [(1, 10), (60, 200), (86400, 100000)],
    "stoxkart": [(1, 10)],
}

KEY_PREFIX = "unified:orders:rate_limit"

class RateLimited(Exception):
    """
    A write would take a broker past one of its order limits.

    Attributes:
        retry_after_seconds (int): How long until the full window turns over.
    """

    def __init__(self, broker, window_seconds, limit, retry_after_seconds):
        period = {1: "second", 60: "minute", 86400: "day"}.get(window_seconds, f"{window_seconds} seconds")
        super().__init__(f"{broker} takes at most {limit} orders a {period}; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds

def _bucket_key(broker, window_seconds, now):
    """
    The Redis counter for one broker's window at one moment, and when that bucket ends.
    """
    bucket = int(now // window_seconds)
    return f"{KEY_PREFIX}:{broker}:{window_seconds}:{bucket}", (bucket + 1) * window_seconds

def has_room(cache, broker):
    """
    Whether a write to a broker would be inside all its limits now, without taking a slot.

    - `cache` is the Redis client.
    - `broker` is the broker name.
    """
    now = time.time()
    for window_seconds, limit in ORDER_WRITE_LIMITS.get(broker, []):
        key, _ = _bucket_key(broker, window_seconds, now)
        count = cache.get(key)
        if count is not None and int(count) >= limit:
            return False
    return True

def take_slot(cache, broker):
    """
    Take a slot in every one of a broker's windows for one write, or raise `RateLimited` having taken none.

    - `cache` is the Redis client.
    - `broker` is the broker name.
    """
    now = time.time()
    taken = []
    for window_seconds, limit in ORDER_WRITE_LIMITS.get(broker, []):
        key, ends_at = _bucket_key(broker, window_seconds, now)
        count = cache.incr(key)
        if count == 1:
            cache.expire(key, window_seconds + 1)
        taken.append(key)
        if count > limit:
            for taken_key in taken:
                cache.decr(taken_key)
            raise RateLimited(broker, window_seconds, limit, max(1, math.ceil(ends_at - now)))
