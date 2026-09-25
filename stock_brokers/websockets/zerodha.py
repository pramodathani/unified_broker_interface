"""
Zerodha's two websockets: Kite's market quotes ticker and the account's order updates.

Both connect to Kite's ticker at `wss://ws.kite.trade`, with the api key and the access token in the URL, so there is no login message.
Kite refuses a dead token at the handshake with HTTP 403 (or 401), which `BrokerWebsocket` answers by logging in again once.

**The login.**
`ZerodhaSession` holds the `ZerodhaAPI` every socket reads its credentials from, and reads them afresh on every connect, so a login made by any process is picked up.
Kite issues one token per session and every login invalidates the last, so the session logs in again one socket at a time, and only when no other socket or process has already replaced the token that failed.

**Quotes.**
`ZerodhaQuotesSocket` subscribes its batch of instrument tokens and puts them in full mode.
Market data arrives as binary frames: a two byte packet count, then each packet after its two byte length.
A packet's length says what it holds:

| Length | Packet |
| --- | --- |
| 8 | Last price |
| 28 | Index quote |
| 32 | Index quote with the exchange timestamp |
| 44 | Quote |
| 184 | Full quote with open interest and five levels of depth on each side |

Every value is a big endian unsigned integer.
The low byte of an instrument token names its exchange segment (738561 is NSE RELIANCE).
Prices are integers, divided into rupees by segment: by 100, by 10,000,000 for NSE currency and by 10,000 for BSE currency.
Index packets carry no quantities, and bytes 24 to 28 of an index packet are the change in points, so the percentage `change` is computed from the last price and the close instead.
Text frames are Kite's own messages; an `error` is logged and the rest are ignored.

**Order updates.**
Kite has no separate order endpoint: order updates arrive as JSON text messages on the same ticker socket.
`ZerodhaOrderUpdatesSocket` subscribes to no instruments, so the only traffic on it is order updates, a quotes reconnect can never drop an order event, and no instrument quota is spent.
Every change to an order arrives as `{"type": "order", "data": {...}}`, the data being Kite's order postback, which is the same object as an order book row.
Binary frames are market data it never subscribed to and are ignored.

Neither socket writes Redis.
The quotes socket hands each frame's ticks to `on_ticks`, and the order socket hands each message's orders to `on_updates`; the scripts in `bin/zerodha/` do the writing.
"""

import json
import struct
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://ws.kite.trade"

SEGMENTS = {
    1: "nse",
    2: "nfo",
    3: "cds",
    4: "bse",
    5: "bfo",
    6: "bcd",
    7: "mcx",
    8: "mcxsx",
    9: "indices",
}

AUTHENTICATION_STATUSES = (
    401,
    403,
)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10

ORDER = "order"


class ZerodhaSession:
    """
    The Kite login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `ZerodhaAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ZerodhaAPI` raises when it cannot log in.
        """
        from stock_brokers.api.zerodha import ZerodhaAPI

        self._api_class = ZerodhaAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._zerodha = ZerodhaAPI()

    def credentials(self):
        """
        The api key and the access token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The api key and the access token, either of which may be None.
        """
        login = self._zerodha._current_login() or {}
        return self._zerodha._settings.get("api_key"), login.get("access_token")

    def log_in_again(self, stale_token):
        """
        Logs in again, unless another socket or process already replaced the token that failed.

        Kite issues one token per session and a login invalidates the one before, so two sockets logging in at once would each knock out the other's token.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `ZerodhaAPI` raises when it cannot log in.
        """
        with self._lock:
            if self.credentials()[1] != stale_token:
                return
            self._logger.warning("Logging in to Zerodha again.")
            self._zerodha = self._api_class()


class ZerodhaQuotesSocket(BrokerWebsocket):
    """
    One Kite ticker websocket carrying the market quotes of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[int]): The batch of Kite instrument tokens.
            names (dict[str, str]): Each token, as text, to the instrument's name, which becomes a tick's `id`.
            session (ZerodhaSession): The shared login.
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

    def _connect(self):
        """
        Opens the websocket with the token in force now and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        api_key, self._token = self._session.credentials()
        url = f"{FEED_URL}/?api_key={api_key}&access_token={self._token}"
        self._websocket_application = websocket.WebSocketApp(
            url,
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
        Subscribes the batch and puts it in full mode.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        websocket_connection.send(json.dumps({"a": "subscribe", "v": self._tokens}))
        websocket_connection.send(json.dumps({"a": "mode", "v": ["full", self._tokens]}))
        self._logger.info(f"{self.name} opened and subscribed to {len(self._tokens)} instrument(s).")

    def _on_error(self, websocket_connection, error):
        """
        Notes a refused token and reports the error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error, which carries `status_code` when the handshake was refused.

        Returns:
            None: This method returns nothing.
        """
        if getattr(error, "status_code", None) in AUTHENTICATION_STATUSES:
            self._authentication_rejected = True
        self._logger.error(f"{self.name} error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Decodes a binary frame into ticks and hands them on, and logs Kite's text errors.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        if not isinstance(message, bytes):
            try:
                payload = json.loads(message)
            except (TypeError, json.JSONDecodeError):
                return
            if isinstance(payload, dict) and payload.get("type") == "error":
                self._logger.error(f"{self.name}: Kite reported an error: {payload.get('data')}")
            return
        ticks = []
        for packet in self._split_packets(message):
            tick = self._parse_packet(packet)
            if tick:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)

    def _split_packets(self, frame):
        """
        Splits a frame into its packets.

        Args:
            frame (bytes): The binary frame: a two byte count, then each packet after its two byte length.

        Returns:
            list[bytes]: The packets, stopping early at a frame that ends before its count says.
        """
        if len(frame) < 2:
            return []
        packets = []
        offset = 2
        for _ in range(self._unpack(frame, 0, 2, "H")):
            if offset + 2 > len(frame):
                break
            length = self._unpack(frame, offset, offset + 2, "H")
            packets.append(frame[offset + 2:offset + 2 + length])
            offset = offset + 2 + length
        return packets

    def _parse_packet(self, packet):
        """
        Builds a normalized tick from one packet.

        Args:
            packet (bytes): The binary packet.

        Returns:
            dict | None: The tick, or None for a packet that carries no tick.
        """
        length = len(packet)
        if length < 8:
            return None
        token = self._unpack(packet, 0, 4)
        exchange = SEGMENTS.get(token & 0xff)
        divisor = self._price_divisor(exchange)

        if length == 8:
            tick = self._empty_tick(token, exchange, "ltp")
            tick["last_price"] = self._unpack(packet, 4, 8) / divisor
            return tick

        if exchange == "indices" and length in (28, 32):
            mode = "full"
            if length == 28:
                mode = "quote"
            tick = self._empty_tick(token, exchange, mode)
            tick["last_price"] = self._unpack(packet, 4, 8) / divisor
            tick["ohlc"] = {
                "high": self._unpack(packet, 8, 12) / divisor,
                "low": self._unpack(packet, 12, 16) / divisor,
                "open": self._unpack(packet, 16, 20) / divisor,
                "close": self._unpack(packet, 20, 24) / divisor,
            }
            self._apply_change(tick)
            if length == 32:
                tick["exchange_timestamp"] = self._unpack(packet, 28, 32)
            return tick

        if length not in (44, 184):
            self._logger.debug(f"{self.name} skipped a packet of unexpected length {length}.")
            return None

        mode = "full"
        if length == 44:
            mode = "quote"
        tick = self._empty_tick(token, exchange, mode)
        tick["last_price"] = self._unpack(packet, 4, 8) / divisor
        tick["last_quantity"] = self._unpack(packet, 8, 12)
        tick["average_price"] = self._unpack(packet, 12, 16) / divisor
        tick["volume"] = self._unpack(packet, 16, 20)
        tick["buy_quantity"] = self._unpack(packet, 20, 24)
        tick["sell_quantity"] = self._unpack(packet, 24, 28)
        tick["ohlc"] = {
            "open": self._unpack(packet, 28, 32) / divisor,
            "high": self._unpack(packet, 32, 36) / divisor,
            "low": self._unpack(packet, 36, 40) / divisor,
            "close": self._unpack(packet, 40, 44) / divisor,
        }
        self._apply_change(tick)

        if length == 184:
            tick["last_trade_time"] = self._unpack(packet, 44, 48)
            tick["oi"] = self._unpack(packet, 48, 52)
            tick["oi_day_high"] = self._unpack(packet, 52, 56)
            tick["oi_day_low"] = self._unpack(packet, 56, 60)
            tick["exchange_timestamp"] = self._unpack(packet, 60, 64)
            level = 0
            for offset in range(64, 184, 12):
                side = "buy"
                if level >= 5:
                    side = "sell"
                tick["depth"][side].append({
                    "quantity": self._unpack(packet, offset, offset + 4),
                    "price": self._unpack(packet, offset + 4, offset + 8) / divisor,
                    "orders": self._unpack(packet, offset + 8, offset + 10, "H"),
                })
                level = level + 1
        return tick

    def _empty_tick(self, token, exchange, mode):
        """
        A tick with every field unset.

        Args:
            token (int): The Kite instrument token.
            exchange (str | None): The segment its low byte names.
            mode (str): `ltp`, `quote` or `full`.

        Returns:
            dict: The tick, named from the batch's names or by its token.
        """
        return {
            "id": self._names.get(str(token)) or str(token),
            "broker": "zerodha",
            "instrument_token": token,
            "exchange": exchange,
            "mode": mode,
            "last_price": None,
            "last_quantity": None,
            "average_price": None,
            "volume": None,
            "buy_quantity": None,
            "sell_quantity": None,
            "ohlc": {
                "open": None,
                "high": None,
                "low": None,
                "close": None,
            },
            "change": None,
            "oi": None,
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": None,
            "exchange_timestamp": None,
            "depth": {
                "buy": [],
                "sell": [],
            },
            "received_at": time.time(),
        }

    def _unpack(self, data, start, end, byte_format="I"):
        """
        A big endian value from a slice of a packet.

        Args:
            data (bytes): The packet or frame.
            start (int): Where the slice starts.
            end (int): Where the slice ends.
            byte_format (str): The `struct` format character, `I` for four bytes and `H` for two.

        Returns:
            int: The value.
        """
        return struct.unpack(">" + byte_format, data[start:end])[0]

    def _price_divisor(self, exchange):
        """
        What Kite's integer prices are divided by to give rupees.

        Args:
            exchange (str | None): The segment the token's low byte names.

        Returns:
            float: The divisor.
        """
        if exchange == "cds":
            return 10000000.0
        if exchange in ("bcd", "bsecds"):
            return 10000.0
        return 100.0

    def _apply_change(self, tick):
        """
        Sets the percentage change of the last price against the close, when there is a close.

        Args:
            tick (dict): The tick to adjust.

        Returns:
            None: This method returns nothing.
        """
        close = tick["ohlc"]["close"]
        if close:
            tick["change"] = (tick["last_price"] - close) * 100 / close
        else:
            tick["change"] = None


class ZerodhaOrderUpdatesSocket(BrokerWebsocket):
    """
    A Kite ticker websocket subscribed to nothing, carrying the account's order updates.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (ZerodhaSession): The login.
            on_updates (callable): Called on this socket's thread with each message's Kite orders, as a list of dictionaries exactly as Kite sent them, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates
        self._token = None

    def _connect(self):
        """
        Opens the websocket with the token in force now and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        api_key, self._token = self._session.credentials()
        url = f"{FEED_URL}/?api_key={api_key}&access_token={self._token}"
        self._websocket_application = websocket.WebSocketApp(
            url,
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
        Logs in again through the session, which skips the login when the token was already replaced.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again(self._token)

    def _on_open(self, websocket_connection):
        """
        Subscribes to nothing: without a subscription Kite pushes order updates and no market data.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._logger.info(f"{self.name} opened. Waiting for order updates.")

    def _on_error(self, websocket_connection, error):
        """
        Notes a refused token and reports the error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error, which carries `status_code` when the handshake was refused.

        Returns:
            None: This method returns nothing.
        """
        if getattr(error, "status_code", None) in AUTHENTICATION_STATUSES:
            self._authentication_rejected = True
        self._logger.error(f"Order updates error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Hands a message's order updates on, logs Kite's errors, and ignores everything else.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The frame: one JSON message, or a JSON list of them.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            return

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
            if entry.get("type") == ORDER:
                orders.append(entry.get("data"))
            elif entry.get("type") == "error":
                self._logger.error(f"Kite reported an error: {entry.get('data')}")
            else:
                self._logger.info(f"Ignoring a message of type {entry.get('type')!r}: {json.dumps(entry)[:200]}")
        if orders:
            self._on_updates(orders, received_at)
