"""
The reconnect loop every broker's websocket shares.

A broker's quotes socket and order updates socket live in `stock_brokers/websockets/<broker>.py` and subclass `BrokerWebsocket`.
The subclass writes what is particular to its broker: how to open the connection and block until it closes (`_connect`), how to log in again after a refusal (`_log_in_again`), and how to read the broker's frames.
This class holds the loop around them, which is the same for every broker:

1. Connect, and block until the connection closes.
2. A connection that opened and was not refused resets the failure count and the backoff.
3. A refused handshake, or six failed connects in a row, logs in again once before connecting again.
4. Still failing after that login, the socket gives up: `gave_up` is set and `run_forever` returns, so the script can exit 1 and let systemd restart it.
5. Otherwise wait, doubling the wait from 1 second up to 60, and connect again.

The loop never touches Redis.
A socket hands what it decodes to a function its script gives it, and the script does the writing.
"""

import threading


class BrokerWebsocket:
    """
    One websocket to a broker that reconnects until it is closed or cannot recover.

    Attributes:
        name (str): The socket's name, which starts every line it logs.
        gave_up (bool): Whether the socket stopped because it could not recover.
    """

    MIN_BACKOFF_SECONDS = 1
    MAX_BACKOFF_SECONDS = 60
    MAX_FAILED_CONNECTS = 6

    def __init__(self, name, logger):
        """
        Sets up a socket that has not connected yet.

        Args:
            name (str): The socket's name, which starts every line it logs.
            logger (logging.Logger): Where the socket reports.

        Returns:
            None: This method returns nothing.
        """
        self.name = name
        self.gave_up = False
        self._logger = logger
        self._stop = threading.Event()
        self._websocket_application = None
        self._opened = False
        self._authentication_rejected = False

    def close(self):
        """
        Closes the connection and stops reconnecting.

        Returns:
            None: This method returns nothing.
        """
        self._stop.set()
        if self._websocket_application is not None:
            self._websocket_application.close()

    def run_forever(self):
        """
        Connects, and reconnects with backoff, until closed or unable to recover.

        Returns:
            None: This method returns nothing. `gave_up` says whether the socket stopped because it could not recover.
        """
        backoff = self.MIN_BACKOFF_SECONDS
        failed_connects = 0
        logged_in_again = False
        while not self._stop.is_set():
            self._opened = False
            self._authentication_rejected = False
            try:
                self._connect()
            except Exception as exception:
                self._logger.error(f"{self.name} connection failed: {type(exception).__name__}: {exception}")
            if self._stop.is_set():
                break

            if self._opened and not self._authentication_rejected:
                failed_connects = 0
                logged_in_again = False
                backoff = self.MIN_BACKOFF_SECONDS
            else:
                failed_connects = failed_connects + 1

            if self._authentication_rejected or failed_connects >= self.MAX_FAILED_CONNECTS:
                if logged_in_again and self._gives_up_after_logging_in_again(failed_connects):
                    self.gave_up = True
                    self._logger.error(f"{self.name} still cannot connect after logging in again. Giving up.")
                    break
                try:
                    self._log_in_again()
                except Exception as exception:
                    self.gave_up = True
                    self._logger.error(f"{self.name} could not log in again: {type(exception).__name__}: {exception}")
                    break
                failed_connects = 0
                logged_in_again = True

            self._logger.warning(f"{self.name} disconnected. Reconnecting in {backoff} seconds.")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, self.MAX_BACKOFF_SECONDS)
        self._logger.info(f"{self.name} stopped.")

    def _gives_up_after_logging_in_again(self, failed_connects):
        """
        Whether a socket that has already logged in again gives up on this failure.

        The loop asks only when the connection was refused or has failed six times in a row.
        By default the answer is yes, so a refusal straight after logging in again ends the socket.
        A broker whose refusals are not always about the login overrides this to give up only after six more failed connects.

        Args:
            failed_connects (int): How many connects in a row have failed since the last login.

        Returns:
            bool: True to give up now.
        """
        return True

    def _connect(self):
        """
        Opens the connection with the credentials in force now and blocks until it closes.

        A subclass sets `_opened` when the connection opens and `_authentication_rejected` when the broker refuses the credentials.

        Returns:
            None: This method returns nothing.

        Raises:
            NotImplementedError: Always, until a subclass implements it.
        """
        raise NotImplementedError

    def _log_in_again(self):
        """
        Logs in again after the broker refused the credentials, unless another process already has.

        Returns:
            None: This method returns nothing.

        Raises:
            NotImplementedError: Always, until a subclass implements it.
        """
        raise NotImplementedError

    def _on_close(self, websocket_connection, status_code, message):
        """
        Reports that the connection closed.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that closed.
            status_code (int | None): The close status the broker sent.
            message (str | None): The close reason the broker sent.

        Returns:
            None: This method returns nothing.
        """
        self._logger.info(f"{self.name} closed with status {status_code}: {message}")
