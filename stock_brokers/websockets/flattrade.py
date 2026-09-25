"""
Flattrade's two websockets on the Noren platform: the market feed and the account's order updates.

Both connect to `wss://piconnect.flattrade.in/PiConnectWSTp/`, a separate connection each.
Flattrade permits only one websocket per session, so in production the order updates socket is not run and orders come from the poller alone.

**The login.**
`FlattradeSession` holds the `FlattradeAPI` both sockets read their credentials from, afresh on every connect, so a login made by any process is picked up.
Noren refuses a dead session inside an HTTP 200, so a constructor that returned is no proof of a working one: every login is confirmed by calling `UserDetails`, and a session it refuses raises.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed.
The order socket logs in again whenever it is refused, without that check, as it always has.

**The connect frame.**
Noren streams JSON text, and a connection is unusable until it is authenticated.
On open a socket sends `{"t": "a", "uid", "actid", "source": "API", "accesstoken"}` with the account's user id.
The frame is `a` with the token named `accesstoken`: Noren also accepts a `c` frame naming it `susertoken`, and answers that `NOT_OK` for a token REST accepts, which reads like an expired session and is not one.
Only after the `ak` acknowledgement says `OK` (documented as "Ok" at one Noren broker and "OK" at another, so compared without case) does the socket subscribe; any other answer is a refused login.
Noren's own heartbeat, `{"t":"h"}`, is sent every three seconds as the ping payload, because a plain websocket ping on the default interval is not enough and the server drops the connection.

**Quotes.**
`FlattradeQuotesSocket` subscribes its batch with one `{"t": "d", "k": "NSE|2885#MCX|565899"}` frame, for depth and touchline together.
The feed is incremental: an acknowledgement (`tk`, `dk`) carries every field and each update after it (`tf`, `df`) only what changed, so the last state of each instrument is kept and every update merged into it before a tick is built.
Every value arrives as a string and is converted, with blanks and `NA` as None.
An acknowledgement names the instrument with its trading symbol, and a name that differs from the one held is handed to `on_names` before the frame's ticks.
Noren spells `ltt` as an epoch, a date and time, or a bare India clock time; all three become an epoch, a bare clock time dated by the tick's feed time and moved back a day when it would otherwise be after it.
No tick is handed on until an instrument has a price.

**Order updates.**
`FlattradeOrderUpdatesSocket` subscribes to the whole account with `{"t": "o", "actid": <user id>}`, and every change to an order then arrives as an `om` message carrying the order book's fields.

Neither socket writes Redis.
The quotes socket hands each frame's new names to `on_names` and its ticks to `on_ticks`, and the order socket hands each frame's `om` updates to `on_updates`; the scripts in `bin/flattrade/` do the writing.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"
USER_DETAILS_URL = "https://piconnect.flattrade.in/PiConnectAPI/UserDetails"

CONNECT_ACK = "ak"
TOUCHLINE_ACK = "tk"
TOUCHLINE_FEED = "tf"
DEPTH_ACK = "dk"
DEPTH_FEED = "df"
ORDER_UPDATE = "om"

HEARTBEAT_PAYLOAD = '{"t":"h"}'
HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TIMEOUT_SECONDS = 2

INDIA = timezone(timedelta(hours=5, minutes=30))
TRADE_TIME_FORMATS = (
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


class FlattradeSession:
    """
    The Flattrade login every socket authenticates with, confirmed against UserDetails and logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `FlattradeAPI`, which logs in when the stored session is dead, and confirms the session.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When UserDetails refuses the session.
            Exception: Whatever `FlattradeAPI` raises when it cannot log in.
        """
        from stock_brokers.api.flattrade import FlattradeAPI

        self._api_class = FlattradeAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._flattrade = FlattradeAPI()
        self._confirm()

    def credentials(self):
        """
        The user id and the access token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The user id and the access token, either of which may be None.
        """
        login = self._flattrade._current_login() or {}
        return self._flattrade._settings.get("username"), login.get("access_token")

    def log_in_again(self, stale_token):
        """
        Logs in again and confirms the session, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When UserDetails refuses the new session.
            Exception: Whatever `FlattradeAPI` raises when it cannot log in.
        """
        with self._lock:
            if self.credentials()[1] != stale_token:
                return
            self._log_in()

    def log_in_again_without_checking(self):
        """
        Logs in again and confirms the session, whether or not the token was already replaced.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When UserDetails refuses the new session.
            Exception: Whatever `FlattradeAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `FlattradeAPI` again and confirms the session; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When UserDetails refuses the new session.
            Exception: Whatever `FlattradeAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Flattrade again.")
        self._flattrade = self._api_class()
        self._confirm()

    def _confirm(self):
        """
        Checks that UserDetails serves the session, since Noren refuses a dead session inside an HTTP 200.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When UserDetails refuses the session.
        """
        data = (self._flattrade.post(url=USER_DETAILS_URL, timeout=10) or {}).get("data")
        if not isinstance(data, dict) or str(data.get("stat", "")).lower() != "ok":
            raise RuntimeError(f"UserDetails refused the session: {str(data)[:200]}")


class FlattradeQuotesSocket(BrokerWebsocket):
    """
    One Noren market feed websocket carrying the touchline and depth of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_names, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `EXCHANGE|TOKEN` instrument tokens.
            names (dict[str, str]): Each token to the instrument's name, shared between sockets and updated as Noren names instruments.
            session (FlattradeSession): The shared login.
            on_names (callable): Called with a dictionary of tokens to their new names when a frame names instruments, on this socket's thread.
            on_ticks (callable): Called with each frame's list of ticks, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._tokens = tokens
        self._names = names
        self._session = session
        self._on_names = on_names
        self._on_ticks = on_ticks
        self._token = None
        self._user_id = None
        self._state = {}

    def _connect(self):
        """
        Opens the websocket with the credentials in force now and blocks until it closes, sending Noren's heartbeat meanwhile.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        self._user_id, self._token = self._session.credentials()
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
            ping_payload=HEARTBEAT_PAYLOAD,
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
        Sends the connect frame; the subscription waits for its acknowledgement.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._state = {}
        websocket_connection.send(json.dumps({
            "t": "a",
            "uid": self._user_id,
            "actid": self._user_id,
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
        Handles one Noren frame, handing its new names on first and then its ticks.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        ticks, named = self._parse(message)
        if named:
            self._on_names(named)
        if ticks:
            self._on_ticks(ticks)

    def _parse(self, message):
        """
        Reads one Noren frame, subscribing on the connect acknowledgement and learning names on the way.

        Args:
            message (bytes | str): The frame.

        Returns:
            tuple: The frame's ticks as a list, and the instruments it newly names as a dictionary of token to name.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            self._logger.warning(f"{self.name} could not decode a frame: {str(message)[:200]}")
            return [], {}
        if not isinstance(payload, dict):
            return [], {}

        message_type = payload.get("t")
        if message_type == CONNECT_ACK:
            if str(payload.get("s", "")).upper() == "OK":
                self._websocket_application.send(json.dumps({"t": "d", "k": "#".join(self._tokens)}))
                self._logger.info(f"{self.name} authenticated and subscribed to {len(self._tokens)} instrument(s).")
            else:
                self._logger.error(f"{self.name} authentication rejected: {payload}")
                self._authentication_rejected = True
                self._websocket_application.close()
            return [], {}

        if message_type not in (TOUCHLINE_ACK, TOUCHLINE_FEED, DEPTH_ACK, DEPTH_FEED):
            return [], {}
        exchange = payload.get("e")
        token = payload.get("tk")
        if not exchange or not token:
            return [], {}
        instrument_token = f"{exchange}|{token}"

        named = {}
        if message_type in (TOUCHLINE_ACK, DEPTH_ACK) and payload.get("ts"):
            name = f"{exchange}:{payload['ts']}"
            if self._names.get(instrument_token) != name:
                self._names[instrument_token] = name
                named[instrument_token] = name

        state = self._state.setdefault(instrument_token, {})
        for field, value in payload.items():
            if field not in ("t", "e", "tk"):
                state[field] = value
        tick = self._build_tick(instrument_token, state, self._names.get(instrument_token))
        if tick["last_price"] is None:
            return [], named
        return [tick], named

    def _build_tick(self, instrument_token, state, name):
        """
        Builds a normalized tick from the merged state of an instrument.

        Args:
            instrument_token (str): The `EXCHANGE|TOKEN` key.
            state (dict): The instrument's merged fields.
            name (str | None): The instrument's name, or None to key the tick by its token.

        Returns:
            dict: The tick.
        """
        exchange = instrument_token.partition("|")[0]
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
            if state.get(f"bp{level}") is not None:
                depth["buy"].append({
                    "quantity": self._number(state.get(f"bq{level}"), int),
                    "price": self._number(state.get(f"bp{level}")),
                    "orders": self._number(state.get(f"bo{level}"), int),
                })
            if state.get(f"sp{level}") is not None:
                depth["sell"].append({
                    "quantity": self._number(state.get(f"sq{level}"), int),
                    "price": self._number(state.get(f"sp{level}")),
                    "orders": self._number(state.get(f"so{level}"), int),
                })

        mode = "quote"
        if depth["buy"] or depth["sell"]:
            mode = "full"
        feed_time = self._number(state.get("ft"), int)
        return {
            "id": name or instrument_token,
            "broker": "flattrade",
            "instrument_token": instrument_token,
            "exchange": exchange,
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
        A Noren string field as a number, treating blanks and placeholders as missing.

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
        Noren's last trade time as an epoch, whichever way it is spelled.

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


class FlattradeOrderUpdatesSocket(BrokerWebsocket):
    """
    Flattrade's Noren order update websocket, subscribed to the whole account once authenticated.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (FlattradeSession): The login.
            on_updates (callable): Called on this socket's thread with each frame's `om` updates that carry an order number, as dictionaries exactly as Noren sent them, and the `datetime` the frame was received.
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
            ping_payload=HEARTBEAT_PAYLOAD,
        )

    def _log_in_again(self):
        """
        Logs in again and confirms the session, without checking whether another process already replaced the token.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Sends the connect frame with the token in force now; the subscription waits for its acknowledgement.

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
        Subscribes once authenticated, and hands each frame's order updates on.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
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
                    self._logger.info("Authenticated and subscribed to order updates. Waiting for order updates.")
                else:
                    self._logger.error(f"Authentication rejected: {entry}")
                    self._authentication_rejected = True
                    websocket_connection.close()
            elif message_type == ORDER_UPDATE and entry.get("norenordno"):
                orders.append(entry)
            else:
                self._logger.debug(f"Ignoring a message of type {message_type!r}: {json.dumps(entry)[:200]}")
        if orders:
            self._on_updates(orders, received_at)
