"""A background thread that keeps one broker's pooled connection freshly used, so an order does not pay for a new TLS handshake."""

import threading


class ConnectionWarmer:
    """Pings one broker's host every `WARM_INTERVAL_SECONDS` through that broker's order session, on a daemon thread of its own.

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
        """Pings until stopped, waiting `WARM_INTERVAL_SECONDS` between pings.

        Returns:
            None: This method returns nothing.
        """
        while not self.stop_event.is_set():
            self.ping()
            self.stop_event.wait(self.broker_orders.WARM_INTERVAL_SECONDS)

    def ping(self):
        """Sends one ping, catching anything it raises.

        This is the isolation point that keeps the warmer apart from orders, so it catches every `Exception`.

        Returns:
            None: This method returns nothing.
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
            return
        if self.failing:
            self.logger.info(
                'warming the order connection to %s works again',
                broker_name,
            )
        self.failing = False
