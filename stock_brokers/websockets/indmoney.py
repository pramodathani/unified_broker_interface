"""
INDmoney's two websockets: the INDstocks price feed and the account's order updates.

**The login.**
`IndmoneySession` holds the `INDMoneyAPI` both sockets read their credentials from, afresh on every connect, so a login made by any process is picked up.
The token travels in the handshake as `Authorization`, with the client id as `x-api-key` when there is one, and INDstocks refuses a dead token at the handshake itself with HTTP 401, 403 or 513.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed.
The order socket logs in again whenever it is refused, without that check, as it always has.

**Quotes.**
`IndmoneyQuotesSocket` connects to `wss://ws-prices.indstocks.com/api/v1/ws/prices` and subscribes its batch in `full` mode, the richest the feed serves: `ltp` carries only the last price, `quote` carries the day's open, high, low, close and volume without a last price, and `depth`, `market_depth`, `depth5` and `snapquote` send nothing.
Every update arrives as a JSON string whose content is itself JSON, followed by a newline, so each line of a frame is decoded twice.
An update names the instrument by its bare security id, a millisecond `timestamp`, and a `data` object carrying only what changed, so each instrument's fields are merged across updates.
Every socket carries instruments of one segment only, because only the socket's segment places a bare security id.
A message without `data` is logged rather than silently dropped, and no tick is handed on until an instrument has a last price.
`close` is sent as the last price, not the previous close, and the best bid and offer are the only depth, without quantities.

**Order updates.**
`IndmoneyOrderUpdatesSocket` connects to `wss://ws-order-updates.indstocks.com/api/v1/ws/trades` and asks for `order_update` messages.
Subscription acknowledgements and heartbeats share the connection; an order arrives as `{"type": "order", "data": {...}}`, or with the order's fields beside `type` when there is no `data` object.

Neither socket writes Redis.
The quotes socket hands each frame's ticks to `on_ticks`, and the order socket hands each message's orders to `on_updates`; the scripts in `bin/indmoney/` do the writing.
"""

import json
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
ORDER_UPDATES_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

SUBSCRIPTION_MODE = "full"
ORDER = "order"

AUTHENTICATION_STATUS_CODES = (
    401,
    403,
    513,
)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class IndmoneySession:
    """
    The INDmoney login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `INDMoneyAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `INDMoneyAPI` raises when it cannot log in.
        """
        from stock_brokers.api.indmoney import INDMoneyAPI

        self._api_class = INDMoneyAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._indmoney = INDMoneyAPI()

    def credentials(self):
        """
        The api key (client id) and the access token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The client id and the access token, either of which may be None.
        """
        login = self._indmoney._current_login() or {}
        return self._indmoney._settings.get("client_id"), login.get("access_token")

    def handshake_headers(self):
        """
        The headers that present the credentials in force now in the websocket handshake.

        Returns:
            tuple: The headers as a dictionary, and the access token they carry.
        """
        client_id, token = self.credentials()
        headers = {
            "Authorization": str(token),
        }
        if client_id:
            headers["x-api-key"] = str(client_id)
        return headers, token

    def log_in_again(self, stale_token):
        """
        Logs in again, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `INDMoneyAPI` raises when it cannot log in.
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
            Exception: Whatever `INDMoneyAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `INDMoneyAPI` again; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `INDMoneyAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to INDmoney again.")
        self._indmoney = self._api_class()


class IndmoneyQuotesSocket(BrokerWebsocket):
    """
    One INDstocks price feed websocket carrying the full quotes of a batch of instruments of one segment.
    """

    def __init__(self, name, tokens, names, session, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `SEGMENT:TOKEN` instrument tokens, all of one segment.
            names (dict[str, str]): Each token to the instrument's name, which becomes a tick's `id`.
            session (IndmoneySession): The shared login.
            on_ticks (callable): Called with each frame's list of ticks, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._tokens = tokens
        self._names = names
        self._session = session
        self._on_ticks = on_ticks
        self._token = None
        self._state = {}

    def _connect(self):
        """
        Opens the websocket with the token in force now, presented in the handshake, and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        headers, self._token = self._session.handshake_headers()
        self._websocket_application = websocket.WebSocketApp(
            FEED_URL,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
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
        Subscribes the batch in full mode.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._state = {}
        websocket_connection.send(json.dumps({
            "action": "subscribe",
            "mode": SUBSCRIPTION_MODE,
            "instruments": list(self._tokens),
        }))
        self._logger.info(f"{self.name} opened and subscribed to {len(self._tokens)} instrument(s) in {SUBSCRIPTION_MODE} mode.")

    def _on_error(self, websocket_connection, error):
        """
        Takes a refused handshake as a dead session, and reports any other error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error, which carries `status_code` when the handshake was refused.

        Returns:
            None: This method returns nothing.
        """
        status = getattr(error, "status_code", None)
        if status in AUTHENTICATION_STATUS_CODES:
            self._authentication_rejected = True
            self._logger.warning(f"{self.name} handshake refused with HTTP {status}, taken as a dead session.")
            return
        self._logger.error(f"{self.name} error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Decodes a frame into ticks and hands them on.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        ticks = self._parse_ticks(message)
        if ticks:
            self._on_ticks(ticks)

    def _decode_entries(self, message):
        """
        Decodes one frame into its update dictionaries, decoding a line a second time when it holds a JSON string.

        Args:
            message (bytes | str): The frame.

        Returns:
            list[dict]: The decoded updates, in order.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        if not isinstance(message, str):
            return []

        entries = []
        for line in message.splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, str):
                    payload = json.loads(payload)
            except json.JSONDecodeError:
                self._logger.debug(f"{self.name} ignored a line that is not JSON: {line[:120]}")
                continue
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        entries.append(item)
            elif isinstance(payload, dict):
                entries.append(payload)
        return entries

    def _parse_ticks(self, message):
        """
        Builds the ticks in one frame, merging each instrument's fields across updates.

        Args:
            message (bytes | str): The frame.

        Returns:
            list[dict]: One tick per update that left its instrument with a last price.
        """
        ticks = []
        for entry in self._decode_entries(message):
            data = entry.get("data")
            instrument = entry.get("instrument")
            if not isinstance(data, dict) or instrument is None:
                self._logger.info(f"{self.name} message without instrument data: {json.dumps(entry)[:200]}")
                continue

            instrument = str(instrument)
            if ":" in instrument:
                token = instrument
            else:
                token = self._subscribed_token(instrument)
            state = self._state.setdefault(token, {})
            state.update(data)
            if entry.get("timestamp") is not None:
                state["timestamp"] = entry["timestamp"]

            tick = self._build_tick(token, state)
            if tick["last_price"] is None:
                continue
            ticks.append(tick)
        return ticks

    def _subscribed_token(self, bare):
        """
        The subscribed `SEGMENT:TOKEN` for a bare security id; a socket carries one segment, so at most one matches.

        Args:
            bare (str): The security id as the feed sent it.

        Returns:
            str: The subscribed token, or the bare id when this socket did not subscribe it.
        """
        for token in self._tokens:
            if token.endswith(f":{bare}"):
                return token
        return bare

    def _epoch_seconds(self, value):
        """
        A feed time as whole epoch seconds.

        Args:
            value (int | float | str | None): The time as sent, in milliseconds, or in seconds for a small value.

        Returns:
            int | None: Epoch seconds, or None for a missing or zero time.
        """
        moment = self._number(value)
        if not moment:
            return None
        if moment > 1e11:
            return int(moment / 1000)
        return int(moment)

    def _build_tick(self, token, state):
        """
        Builds a normalized tick from an instrument's merged full mode fields.

        Args:
            token (str): The instrument's `SEGMENT:TOKEN`.
            state (dict): Its fields merged across updates, with the latest update's `timestamp`.

        Returns:
            dict: The tick.
        """
        buy_levels = []
        bid_price = self._number(state.get("bid_price"))
        if bid_price is not None:
            buy_levels.append({
                "quantity": None,
                "price": bid_price,
                "orders": None,
            })
        sell_levels = []
        ask_price = self._number(state.get("ask_price"))
        if ask_price is not None:
            sell_levels.append({
                "quantity": None,
                "price": ask_price,
                "orders": None,
            })

        exchange = None
        if ":" in token:
            exchange = token.split(":", 1)[0]
        return {
            "id": self._names.get(token) or token,
            "broker": "indmoney",
            "instrument_token": token,
            "exchange": exchange,
            "mode": "quote",
            "last_price": self._number(state.get("ltp")),
            "last_quantity": None,
            "average_price": None,
            "volume": self._whole(state.get("volume")),
            "buy_quantity": self._whole(state.get("total_buy_qty")),
            "sell_quantity": self._whole(state.get("total_sell_qty")),
            "ohlc": {
                "open": self._number(state.get("open")),
                "high": self._number(state.get("high")),
                "low": self._number(state.get("low")),
                "close": self._number(state.get("close")),
            },
            "change": None,
            "oi": self._whole(state.get("oi")),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": self._epoch_seconds(state.get("ltt")),
            "exchange_timestamp": self._epoch_seconds(state.get("timestamp")),
            "depth": {
                "buy": buy_levels,
                "sell": sell_levels,
            },
            "received_at": time.time(),
        }

    def _number(self, value):
        """
        A feed value as a float.

        Args:
            value (object): The raw value.

        Returns:
            float | None: The number, or None for a blank, null or unreadable value.
        """
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _whole(self, value):
        """
        A feed quantity as an integer; quantities are counts, so a float such as 12.0 becomes 12.

        Args:
            value (object): The raw value.

        Returns:
            int | None: The count, or None.
        """
        value = self._number(value)
        if value is None:
            return None
        return int(round(value))


class IndmoneyOrderUpdatesSocket(BrokerWebsocket):
    """
    INDstocks' order update websocket, authenticated by its handshake.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (IndmoneySession): The login.
            on_updates (callable): Called on this socket's thread with each message's orders, as dictionaries exactly as INDstocks sent them, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates

    def _connect(self):
        """
        Opens the websocket with the token in force now, presented in the handshake, and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        headers, _ = self._session.handshake_headers()
        self._websocket_application = websocket.WebSocketApp(
            ORDER_UPDATES_URL,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
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
        Asks for order updates; the session is already authenticated by the handshake.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        websocket_connection.send(json.dumps({"action": "subscribe", "mode": "order_update"}))
        self._logger.info(f"{self.name} opened and subscribed. Waiting for order updates.")

    def _on_error(self, websocket_connection, error):
        """
        Takes a refused handshake as a dead session, and reports any other error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error, which carries `status_code` when the handshake was refused.

        Returns:
            None: This method returns nothing.
        """
        status = getattr(error, "status_code", None)
        if status in AUTHENTICATION_STATUS_CODES:
            self._authentication_rejected = True
            self._logger.warning(f"Order updates handshake refused with HTTP {status}, taken as a dead session.")
            return
        self._logger.error(f"Order updates error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Hands a message's orders on, and logs acknowledgements and anything else.

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
            if entry.get("type") != ORDER:
                if entry.get("status") in ("subscribed", "success") or entry.get("action") == "subscribe":
                    self._logger.info("Order subscription acknowledged.")
                else:
                    self._logger.info(f"Ignoring a message of type {entry.get('type')!r}: {json.dumps(entry)[:200]}")
                continue
            if isinstance(entry.get("data"), dict):
                orders.append(entry.get("data"))
            else:
                orders.append(entry)
        if orders:
            self._on_updates(orders, received_at)
