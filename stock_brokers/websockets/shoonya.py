"""
Shoonya's two websockets on the Noren platform: the market feed and the account's order updates.

Both connect to `wss://api.shoonya.com/NorenWSTP/`, a separate connection each, so a market data reconnect can never drop an order event.

**The login.**
`ShoonyaSession` holds the `ShoonyaAPI` both sockets read their credentials from, afresh on every connect, so a login made by any process is picked up.
Shoonya's login is a headless Chrome session, so the quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed.
The order socket logs in again whenever it is refused, without that check, as it always has.

**The connect frame.**
Noren streams JSON text, and a connection is unusable until it is authenticated.
On open a socket sends `{"t": "a", "uid", "actid", "source": "API", "accesstoken"}` with the account's UCC code as the user id.
The frame is `a` with the token named `accesstoken`: Noren also parses a `c` frame naming it `susertoken`, and refuses a perfectly good token that way, which reads exactly like an expired session.
Only after the `ak` acknowledgement says `OK` (documented as "Ok" and seen as "OK", so compared without case) does the socket subscribe; any other answer is a refused login.
Noren's own heartbeat, `{"t":"h"}`, is sent every three seconds as the ping payload, because a plain websocket ping is not enough to keep the connection.

**Quotes.**
`ShoonyaQuotesSocket` subscribes its batch with one `{"t": "d", "k": "NSE|2885#MCX|565899"}` frame, for depth and touchline together.
The feed is incremental: an acknowledgement (`tk`, `dk`) carries every field and each update after it (`tf`, `df`) only what changed, so the last state of each instrument is kept and every update merged into it before a tick is built.
Every value arrives as a string and is converted, with blanks and `NA` as None.
An acknowledgement names the instrument with its trading symbol; a name the socket did not already have is handed to `on_name` before the tick.
Noren spells `ltt` as an epoch, a date and time, or a bare India clock time; all three become an epoch, a bare clock time dated by the tick's feed time and moved back a day when it would otherwise be after it, which happens for a trade just before midnight reported just after.
No tick is handed on until an instrument has a price.

**Order updates.**
`ShoonyaOrderUpdatesSocket` subscribes to the whole account with `{"t": "o", "actid": <ucc code>}`, and every change to an order then arrives as an `om` message carrying the order book's fields, every value a string.

Neither socket writes Redis.
The quotes socket hands names to `on_name` and each tick to `on_tick`, and the order socket hands each message's `om` updates to `on_updates`; the scripts in `bin/shoonya/` do the writing.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://api.shoonya.com/NorenWSTP/"

CONNECT_ACK = "ak"
TICK_MESSAGES = (
    "tk",
    "tf",
    "dk",
    "df",
)
ACKNOWLEDGEMENTS = (
    "tk",
    "dk",
)
ORDER_UPDATE = "om"

HEARTBEAT = '{"t":"h"}'
HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TIMEOUT_SECONDS = 2

INDIA = timezone(timedelta(hours=5, minutes=30))
TRADE_TIME_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


class ShoonyaSession:
    """
    The Shoonya login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `ShoonyaAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ShoonyaAPI` raises when it cannot log in.
        """
        from stock_brokers.api.shoonya import ShoonyaAPI

        self._api_class = ShoonyaAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._shoonya = ShoonyaAPI()

    def credentials(self):
        """
        The Noren user id and the session token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The UCC code and the session token, either of which may be None.
        """
        login = self._shoonya._current_login() or {}
        return self._shoonya._settings.get("ucc_code"), login.get("access_token")

    def log_in_again(self, stale_token):
        """
        Logs in again, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The session token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ShoonyaAPI` raises when it cannot log in.
        """
        with self._lock:
            if self.credentials()[1] != stale_token:
                return
            self._log_in()

    def log_in_again_without_checking(self):
        """
        Logs in again whether or not the token was already replaced.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ShoonyaAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `ShoonyaAPI` again; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ShoonyaAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Shoonya again.")
        self._shoonya = self._api_class()


class ShoonyaQuotesSocket(BrokerWebsocket):
    """
    One Noren market feed websocket carrying the touchline and depth of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_name, on_tick, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `EXCHANGE|TOKEN` instrument tokens.
            names (dict[str, str]): Each token to the instrument's name, shared between sockets and added to as Noren names instruments.
            session (ShoonyaSession): The shared login.
            on_name (callable): Called with a token and its new name when an acknowledgement names an instrument, on this socket's thread.
            on_tick (callable): Called with each tick, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._tokens = tokens
        self._names = names
        self._session = session
        self._on_name = on_name
        self._on_tick = on_tick
        self._token = None
        self._state = {}

    def _connect(self):
        """
        Opens the websocket and blocks until it closes, sending Noren's heartbeat meanwhile.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        self._websocket_application = websocket.WebSocketApp(
            FEED_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=HEARTBEAT_INTERVAL_SECONDS,
            ping_timeout=HEARTBEAT_TIMEOUT_SECONDS,
            ping_payload=HEARTBEAT,
        )

    def _log_in_again(self):
        """
        Logs in again through the shared session, which skips the login when the token was already replaced.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again(self._token)

    def _on_open(self, websocket_connection):
        """
        Authenticates with the token in force now; the subscription waits for the acknowledgement.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._state = {}
        user_id, self._token = self._session.credentials()
        websocket_connection.send(json.dumps({
            "t": "a",
            "uid": user_id,
            "actid": user_id,
            "source": "API",
            "accesstoken": self._token,
        }))
        self._logger.info(f"{self.name} opened. Authenticating.")

    def _on_error(self, websocket_connection, error):
        """
        Reports an error; Noren refuses a login in its acknowledgement rather than at the handshake.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"{self.name} error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Handles the connect acknowledgement, and hands each tick on.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The message.

        Returns:
            None: This method returns nothing.
        """
        tick = self._parse(message)
        if tick:
            self._on_tick(tick)

    def _parse(self, message):
        """
        Builds a tick from one Noren message, subscribing on the connect acknowledgement and learning names on the way.

        Args:
            message (bytes | str): The message.

        Returns:
            dict | None: The tick, or None for a message that carries none.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            self._logger.debug(f"{self.name} ignored a frame that is not JSON: {str(message)[:160]}")
            return None
        if not isinstance(payload, dict):
            return None

        message_type = payload.get("t")
        if message_type == CONNECT_ACK:
            if str(payload.get("s", "")).upper() == "OK":
                self._websocket_application.send(json.dumps({"t": "d", "k": "#".join(self._tokens)}))
                self._logger.info(f"{self.name} authenticated and subscribed to {len(self._tokens)} instrument(s).")
            else:
                self._logger.error(f"{self.name} authentication refused: {payload}")
                self._authentication_rejected = True
                self._websocket_application.close()
            return None

        if message_type not in TICK_MESSAGES or not payload.get("e") or not payload.get("tk"):
            return None
        token = f"{payload['e']}|{payload['tk']}"

        if message_type in ACKNOWLEDGEMENTS and payload.get("ts") and not self._names.get(token):
            self._names[token] = f"{payload['e']}:{payload['ts']}"
            self._on_name(token, self._names[token])

        state = self._state.setdefault(token, {})
        for key, value in payload.items():
            if key not in ("t", "e", "tk"):
                state[key] = value
        tick = self._build_tick(token, state, self._names.get(token) or token)
        if tick["last_price"] is None:
            return None
        return tick

    def _build_tick(self, token, state, identifier):
        """
        Builds a normalized tick from an instrument's merged state.

        Args:
            token (str): The instrument's `EXCHANGE|TOKEN`.
            state (dict): Its merged field state.
            identifier (str): The name the tick is keyed by.

        Returns:
            dict: The tick.
        """
        last_price = self._number(state.get("lp"))
        close = self._number(state.get("c"))
        change = self._number(state.get("pc"))
        if change is None and last_price is not None and close:
            change = (last_price - close) * 100 / close

        depth = {
            "buy": [],
            "sell": [],
        }
        for level in range(1, 6):
            for side, prefix in (("buy", "b"), ("sell", "s")):
                if state.get(f"{prefix}p{level}") is not None:
                    depth[side].append({
                        "quantity": self._number(state.get(f"{prefix}q{level}"), int),
                        "price": self._number(state.get(f"{prefix}p{level}")),
                        "orders": self._number(state.get(f"{prefix}o{level}"), int),
                    })

        mode = "quote"
        if depth["buy"] or depth["sell"]:
            mode = "full"
        feed_time = self._number(state.get("ft"), int)
        return {
            "id": identifier,
            "broker": "shoonya",
            "instrument_token": token,
            "exchange": token.partition("|")[0],
            "mode": mode,
            "last_price": last_price,
            "last_quantity": self._number(state.get("ltq"), int),
            "average_price": self._number(state.get("ap")),
            "volume": self._number(state.get("v"), int),
            "buy_quantity": self._number(state.get("tbq"), int),
            "sell_quantity": self._number(state.get("tsq"), int),
            "ohlc": {
                "open": self._number(state.get("o")),
                "high": self._number(state.get("h")),
                "low": self._number(state.get("l")),
                "close": close,
            },
            "change": change,
            "oi": self._number(state.get("oi"), int),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": self._trade_time(state.get("ltt"), feed_time),
            "exchange_timestamp": feed_time,
            "depth": depth,
            "received_at": time.time(),
        }

    def _number(self, value, cast=float):
        """
        A Noren string field as a number, with blanks and placeholders as None.

        Args:
            value (str | None): The raw field.
            cast (type): `float` or `int`.

        Returns:
            float | int | None: The number, or None.
        """
        if value is None or value == "" or value == "NA":
            return None
        try:
            if cast is int:
                return cast(float(value))
            return cast(value)
        except (TypeError, ValueError):
            return None

    def _trade_time(self, value, feed_time):
        """
        Noren's last trade time as an epoch, whether sent as an epoch, a date and time, or a bare India clock time.

        Args:
            value (str | None): The raw `ltt` field.
            feed_time (int | None): The tick's `ft` epoch, or None to date a bare clock time by the wall clock.

        Returns:
            int | None: The epoch, or None when the field cannot be read.
        """
        if value is None or value == "" or value == "NA":
            return None
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        for time_format in TRADE_TIME_FORMATS:
            try:
                return int(datetime.strptime(text, time_format).replace(tzinfo=INDIA).timestamp())
            except ValueError:
                continue
        try:
            clock = datetime.strptime(text, "%H:%M:%S").time()
        except ValueError:
            return None
        reference_epoch = feed_time
        if not reference_epoch:
            reference_epoch = time.time()
        reference = datetime.fromtimestamp(reference_epoch, tz=INDIA)
        moment = datetime.combine(reference.date(), clock, tzinfo=INDIA)
        if moment > reference + timedelta(minutes=5):
            moment = moment - timedelta(days=1)
        return int(moment.timestamp())


class ShoonyaOrderUpdatesSocket(BrokerWebsocket):
    """
    Shoonya's order update websocket, subscribed to the whole account once authenticated.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (ShoonyaSession): The login.
            on_updates (callable): Called on this socket's thread with each message's `om` updates that carry an order number, as dictionaries exactly as Noren sent them, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates
        self._user_id = None

    def _connect(self):
        """
        Opens the websocket and blocks until it closes, sending Noren's heartbeat meanwhile.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        self._websocket_application = websocket.WebSocketApp(
            FEED_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=HEARTBEAT_INTERVAL_SECONDS,
            ping_timeout=HEARTBEAT_TIMEOUT_SECONDS,
            ping_payload=HEARTBEAT,
        )

    def _log_in_again(self):
        """
        Logs in again, without checking whether another process already replaced the token.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Authenticates with the token in force now; the subscription waits for the acknowledgement.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._user_id, token = self._session.credentials()
        websocket_connection.send(json.dumps({
            "t": "a",
            "uid": self._user_id,
            "actid": self._user_id,
            "source": "API",
            "accesstoken": token,
        }))
        self._logger.info(f"{self.name} opened. Authenticating.")

    def _on_error(self, websocket_connection, error):
        """
        Reports an error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"Order updates error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Subscribes on the connect acknowledgement, and hands each message's order updates on.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The frame: one JSON message or a JSON list of them.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            self._logger.debug(f"Ignoring a frame that is not JSON: {str(message)[:160]}")
            return

        received_at = datetime.now()
        entries = payload
        if not isinstance(payload, list):
            entries = [payload]
        orders = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            message_type = entry.get("t")
            if message_type == CONNECT_ACK:
                if str(entry.get("s", "")).upper() == "OK":
                    websocket_connection.send(json.dumps({"t": "o", "actid": self._user_id}))
                    self._logger.info("Authenticated and subscribed. Waiting for order updates.")
                else:
                    self._logger.error(f"Authentication refused: {entry}")
                    self._authentication_rejected = True
                    websocket_connection.close()
            elif message_type == ORDER_UPDATE and entry.get("norenordno"):
                orders.append(entry)
        if orders:
            self._on_updates(orders, received_at)
