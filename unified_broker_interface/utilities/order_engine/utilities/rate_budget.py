"""How many order messages a second may be sent to each broker, shared by the order engine and the REST API."""

import secrets
import threading
import time

RATE_KEY_PREFIX = 'unified:orders:rate:'
GLOBAL_RATE_KEY = 'unified:orders:rate:all'
MICROSECONDS_PER_SECOND = 1000000
RATE_WINDOW_SCRIPT = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000000 + tonumber(now_parts[2])
local window = tonumber(ARGV[1])
local member = ARGV[2]
local longest_wait = 0
for index, key in ipairs(KEYS) do
    local limit = tonumber(ARGV[index + 2])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    if redis.call('ZCARD', key) >= limit then
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local wait = tonumber(oldest[2]) + window - now
        if wait > longest_wait then
            longest_wait = wait
        end
    end
end
if longest_wait > 0 then
    return longest_wait
end
for index, key in ipairs(KEYS) do
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, math.floor(window / 1000) + 1000)
end
return 0
"""


class RateBudget:
    """The limit on how many order messages a second go to each broker, counted over a sliding one-second window.

    Every placement, modification and cancellation counts, because an exchange counts them all. The order engine takes a message here before each request it sends, and the REST API takes one before each modification or cancellation it sends, so both draw on one budget per broker.

    The budget lives in Redis rather than in a process, because two kinds of process send orders: the engine and every gunicorn worker. Each broker has a sorted set, `unified:orders:rate:<broker>`, holding the time of every message sent to it in the last second. A Lua script, which Redis runs as one step, drops the entries older than a second, counts the rest, and either adds the new message or answers how long until the oldest one leaves the window. Times come from the Redis server's clock, so processes whose clocks disagree still count against one timeline.

    A sliding window rather than a token bucket is what makes the limit exact. A bucket that holds ten tokens and earns ten a second can send ten at once and then one every tenth of a second, which is nineteen within one second. The window never lets an eleventh message into any one-second span.

    An optional limit across every broker, `unified:orders:rate:all`, is counted the same way in the same step. It is off unless configured, because the compliance limit is per broker.

    Attributes:
        cache (redis.Redis): The Redis client.
        per_second (float): Messages a second across every broker, or 0 for no such limit.
        per_broker_per_second (float): Messages a second to any one broker, or 0 for no limit.
        wait_seconds (float): The longest a message waits for room before it is refused.
        window_seconds (float): The length of the window the limits are counted over; 1.0 counts per second exactly, and a little more leaves a margin for requests that reach a broker unevenly.
        logger (logging.Logger): The logger.
        script (redis.commands.core.Script): The registered window script.
        counts_lock (threading.Lock): Guards the two counters, which several threads update.
        waited (int): How many messages have waited for room.
        refused (int): How many have been refused because no room came in time.
    """

    def __init__(
        self,
        cache,
        per_second,
        per_broker_per_second,
        wait_seconds,
        logger,
        window_seconds=1.0,
    ):
        """Builds the budget.

        Args:
            cache (redis.Redis): The Redis client.
            per_second (float): Messages in one window across every broker, or 0 for no such limit.
            per_broker_per_second (float): Messages in one window to any one broker, or 0 for no limit.
            wait_seconds (float): The longest a message waits for room.
            logger (logging.Logger): The logger.
            window_seconds (float): The length of the window the limits are counted over.

        Returns:
            None: This method returns nothing.
        """
        self.cache = cache
        self.per_second = per_second
        self.per_broker_per_second = per_broker_per_second
        self.wait_seconds = wait_seconds
        self.window_seconds = window_seconds
        self.logger = logger
        self.script = cache.register_script(RATE_WINDOW_SCRIPT)
        self.counts_lock = threading.Lock()
        self.waited = 0
        self.refused = 0

    def take(self, broker_name, stop=None):
        """Takes room for one message to a broker, waiting a little for room if the last second is full.

        A message waits rather than being refused outright, because a burst arriving within the same tenth of a second is ordinary and a short delay is far better than a refusal the caller has to handle. Only a burst that outlasts the whole wait is refused.

        Args:
            broker_name (str): The broker the message is going to.
            stop (threading.Event | None): Set when the process is stopping, so a wait ends early.

        Returns:
            bool: True when the message may be sent.
        """
        deadline = time.monotonic() + self.wait_seconds
        waited = False
        while True:
            wait_microseconds = self.try_take(broker_name)
            if wait_microseconds <= 0:
                if waited:
                    self.count_waited()
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.count_refused()
                self.logger.warning(
                    f'The order rate budget for {broker_name} was still full '
                    f'after {self.wait_seconds} seconds, so a message was '
                    'refused rather than sent late.'
                )
                return False
            waited = True
            pause_seconds = min(
                remaining,
                max(0.001, wait_microseconds / MICROSECONDS_PER_SECOND),
            )
            if self.pause(pause_seconds, stop):
                self.count_refused()
                return False

    def try_take(self, broker_name):
        """Adds one message to the broker's window if there is room, in one Redis step.

        Args:
            broker_name (str): The broker the message is going to.

        Returns:
            int: 0 when the message was counted, otherwise how many microseconds until there is room.
        """
        keys = []
        limits = []
        if self.per_broker_per_second > 0:
            keys.append(RATE_KEY_PREFIX + broker_name)
            limits.append(self.per_broker_per_second)
        if self.per_second > 0:
            keys.append(GLOBAL_RATE_KEY)
            limits.append(self.per_second)
        if not keys:
            return 0
        arguments = [
            int(self.window_seconds * MICROSECONDS_PER_SECOND),
            secrets.token_hex(8),
        ]
        arguments.extend(limits)
        return int(self.script(keys=keys, args=arguments))

    def pause(self, seconds, stop):
        """Waits, and says whether the process was asked to stop instead.

        Args:
            seconds (float): How long to wait.
            stop (threading.Event | None): Set when the process is stopping.

        Returns:
            bool: True when the process is stopping and the message should not be sent.
        """
        if stop is None:
            time.sleep(seconds)
            return False
        return bool(stop.wait(seconds))

    def count_waited(self):
        """Counts one message that had to wait for room.

        Returns:
            None: This method returns nothing.
        """
        with self.counts_lock:
            self.waited = self.waited + 1

    def count_refused(self):
        """Counts one message refused because no room came in time.

        Returns:
            None: This method returns nothing.
        """
        with self.counts_lock:
            self.refused = self.refused + 1

    def counts(self):
        """What the budget has done in this process, for a shutdown line.

        Returns:
            dict: `waited` and `refused`.
        """
        with self.counts_lock:
            return {
                'waited': self.waited,
                'refused': self.refused,
            }
