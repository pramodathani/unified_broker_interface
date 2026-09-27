"""A background thread that keeps one broker's pooled connection freshly used, so an order does not pay for a new TLS handshake."""

import threading
import time

MINIMUM_PAUSE_SECONDS = 0.05


class ConnectionWarmer:
    """Keeps every connection in one broker's order pool freshly used, pinging them one at a time so each is pinged once every `WARM_INTERVAL_SECONDS`, on a daemon thread of its own.

    Nothing the thread does can reach an order: every exception is caught and logged inside its loop, the ping never touches the session's cookies or headers, and a connection goes back to the pool only after `BrokerOrders.warm_connection` has watched it stay open. A failure is logged when a broker starts failing and when it recovers, not on every ping.

    Attributes:
        broker_orders (BrokerOrders): The broker whose connection is kept warm.
        logger (logging.Logger): Where failures and recoveries are logged.
        stop_event (threading.Event): Set to stop the thread.
        thread (threading.Thread | None): The thread, once started.
        pings (int): How many pings have been attempted.
        failures (int): How many pings raised.
        failing (bool): Whether the latest ping raised.
    """

    def __init__(self, broker_orders, logger):
        """Builds a warmer that has not started.

        Args:
            broker_orders (BrokerOrders): The broker whose connection is kept warm.
            logger (logging.Logger): Where failures and recoveries are logged.

        Returns:
            None: This method returns nothing.
        """
        self.broker_orders = broker_orders
        self.logger = logger
        self.stop_event = threading.Event()
        self.thread = None
        self.pings = 0
        self.failures = 0
        self.failing = False

    def start(self):
        """Starts the thread, unless it is already running.

        Returns:
            None: This method returns nothing.
        """
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self.run,
            name=f'order-connection-warmer-{self.broker_orders.BROKER_NAME}',
            daemon=True,
        )
        self.thread.start()

    def stop(self, timeout_seconds=10.0):
        """Asks the thread to stop and waits for it.

        Args:
            timeout_seconds (float): The longest to wait.

        Returns:
            None: This method returns nothing.
        """
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout_seconds)

    def is_running(self):
        """Whether the thread is alive.

        Returns:
            bool: True while the thread runs.
        """
        return self.thread is not None and self.thread.is_alive()

    def run(self):
        """Fills the pool with one ping per connection, then pings one connection at a time so each is used about once every `WARM_INTERVAL_SECONDS`.

        The pool of a warmed broker hands out the connection that has waited longest, so single pings rotate through every connection in it. A new pool holds only empty places, each of which opens a connection when it is first used, so the first round is sent back to back: without it, orders in the first interval after a start would open those connections themselves.

        Pings are spaced `WARM_INTERVAL_SECONDS` divided by the pool size apart, counted from the start of one ping to the start of the next, because a ping already holds its connection for `WARM_SETTLE_SECONDS`. One round of the pool then takes `WARM_INTERVAL_SECONDS` or the pool size times the settle time, whichever is longer, and each broker's `MAXIMUM_IDLE_SECONDS` has to stay above both. A ping that fails is followed by a pause of the whole interval, as before rotation existed, so a broker that cannot be reached is not pinged in a tight loop.

        Returns:
            None: This method returns nothing.
        """
        pool_size = self.broker_orders.adapter.pool_size
        for _ in range(pool_size):
            if self.stop_event.is_set():
                return
            if not self.ping():
                break
        spacing_seconds = self.broker_orders.WARM_INTERVAL_SECONDS / pool_size
        while not self.stop_event.is_set():
            started_at = time.monotonic()
            if self.ping():
                elapsed_seconds = time.monotonic() - started_at
                pause_seconds = max(
                    MINIMUM_PAUSE_SECONDS,
                    spacing_seconds - elapsed_seconds,
                )
            else:
                pause_seconds = self.broker_orders.WARM_INTERVAL_SECONDS
            self.stop_event.wait(pause_seconds)

    def ping(self):
        """Sends one ping, catching anything it raises.

        This is the isolation point that keeps the warmer apart from orders, so it catches every `Exception`.

        Returns:
            bool: True when the ping was sent and answered, False when it raised.
        """
        broker_name = self.broker_orders.BROKER_NAME
        self.pings = self.pings + 1
        try:
            self.broker_orders.warm_connection()
        except Exception as error:
            self.failures = self.failures + 1
            if not self.failing:
                self.logger.warning(
                    'warming the order connection to %s failed and will be retried: %r',
                    broker_name,
                    error,
                )
            self.failing = True
            return False
        if self.failing:
            self.logger.info(
                'warming the order connection to %s works again',
                broker_name,
            )
        self.failing = False
        return True
