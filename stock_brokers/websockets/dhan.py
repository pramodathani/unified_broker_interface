"""
Dhan's two websockets: the DhanHQ v2 market feed and the account's order update stream.

**The login.**
`DhanSession` holds the `DhanAPI` both sockets read their credentials from, afresh on every connect, so a login made by any process is picked up.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed.
The order socket logs in again whenever it is refused, without that check, as it always has.

**Quotes.**
`DhanQuotesSocket` connects to `wss://api-feed.dhan.co` with the token and client id in the URL, and subscribes its batch in full mode (request code 21), a hundred instruments a message.
Market data arrives as binary messages, and one message may carry several packets back to back.
Every value is little endian, and every packet opens with an eight byte header: the response code, the packet's length, Dhan's numeric exchange segment and the security id.

| Code | Packet | Length |
| --- | --- | --- |
| 2 | Ticker: last price and last trade time | 16 |
| 4 | Quote: the trade fields and the day's open, close, high and low | 50 |
| 5 | Open interest | 12 |
| 6 | Previous close | 16 |
| 8 | Full: the trade fields, open interest and its range, open, close, high, low and five levels of depth | 162 |
| 50 | Disconnect, with a reason code | 10 |

The previous close and open interest arrive in packets of their own.
Written as ticks they would replace the instrument's full tick with one lacking a price, so they are remembered per instrument and folded into the ticks that follow.
The close in Dhan's quote and full packets is the previous close during the session but the day's own close after it, so the previous close packet's value, when there is one, is what `ohlc.close` holds.
Dhan's trade times are India wall clock seconds presented as an epoch, so 19,800 seconds are taken off.
A disconnect packet with code 807 (token expired), 808 (authentication failed) or 809 (token invalid) is a refused login: the socket closes and logs in again.
Other disconnect codes are logged.
The quote socket gives up only after six more failed connects, not on the first refusal after logging in again, because Dhan also disconnects for reasons that are not about the login.

**Order updates.**
`DhanOrderUpdatesSocket` connects to `wss://api-order-update.dhan.co` and sends Dhan's login message, `{"LoginReq": {"MsgCode": 42, "ClientId": ..., "Token": ...}, "UserType": "SELF"}`.
Dhan does not answer a successful login: a good token holds the socket open, and a bad one is answered with a binary rejection frame and a disconnect, so any binary frame is taken as a refused login.
Every change to an order in the account then arrives as a JSON message whose `Type` is `order_alert` and whose `Data` is the order.

Neither socket writes Redis.
The quotes socket hands each message's ticks to `on_ticks`, and the order socket hands each message's order alerts to `on_updates`; the scripts in `bin/dhan/` do the writing.
"""

import json
import struct
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://api-feed.dhan.co"
ORDER_UPDATES_URL = "wss://api-order-update.dhan.co"

SEGMENT_NAMES = {
    0: "IDX_I",
    1: "NSE_EQ",
    2: "NSE_FNO",
    3: "NSE_CURRENCY",
    4: "BSE_EQ",
    5: "MCX_COMM",
    7: "BSE_CURRENCY",
    8: "BSE_FNO",
}

SUBSCRIBE_FULL = 21
MAX_INSTRUMENTS_PER_MESSAGE = 100

TICKER = 2
QUOTE = 4
OPEN_INTEREST = 5
PREVIOUS_CLOSE = 6
FULL = 8
DISCONNECT = 50

AUTHENTICATION_DISCONNECT_CODES = (
    807,
    808,
    809,
)

IST_OFFSET_SECONDS = 19800

LOGIN_MESSAGE_CODE = 42
ORDER_ALERT = "order_alert"

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class DhanSession:
    """
    The Dhan login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `DhanAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `DhanAPI` raises when it cannot log in.
        """
        from stock_brokers.api.dhan import DhanAPI

        self._api_class = DhanAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._dhan = DhanAPI()

    def credentials(self):
        """
        The client id and the access token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The client id and the access token, either of which may be None.
        """
        login = self._dhan._current_login() or {}
        return self._dhan._settings.get("client_id"), login.get("access_token")

    def log_in_again(self, stale_token):
        """
        Logs in again, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `DhanAPI` raises when it cannot log in.
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
            Exception: Whatever `DhanAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `DhanAPI` again; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `DhanAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Dhan again.")
        self._dhan = self._api_class()


class DhanQuotesSocket(BrokerWebsocket):
    """
    One DhanHQ market feed websocket carrying the full quotes of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `SEGMENT:SECURITY_ID` instrument tokens.
            names (dict[str, str]): Each token to the instrument's name, which becomes a tick's `id`.
            session (DhanSession): The shared login.
            on_ticks (callable): Called with each message's list of ticks, on this socket's thread.
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
        self._remembered = {}

    def _gives_up_after_logging_in_again(self, failed_connects):
        """
        Gives up only once six connects in a row have failed, since Dhan also disconnects for reasons other than the login.

        Args:
            failed_connects (int): How many connects in a row have failed since the last login.

        Returns:
            bool: True to give up now.
        """
        return failed_connects >= self.MAX_FAILED_CONNECTS

    def _connect(self):
        """
        Opens the websocket with the token in force now and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        client_id, self._token = self._session.credentials()
        url = f"{FEED_URL}?version=2&token={self._token}&clientId={client_id}&authType=2"
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
        Subscribes the batch in full mode, a hundred instruments a message.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        for start in range(0, len(self._tokens), MAX_INSTRUMENTS_PER_MESSAGE):
            batch = self._tokens[start:start + MAX_INSTRUMENTS_PER_MESSAGE]
            instruments = []
            for token in batch:
                instruments.append({
                    "ExchangeSegment": token.partition(":")[0],
                    "SecurityId": token.partition(":")[2],
                })
            websocket_connection.send(json.dumps({
                "RequestCode": SUBSCRIBE_FULL,
                "InstrumentCount": len(batch),
                "InstrumentList": instruments,
            }))
        self._logger.info(f"{self.name} opened and subscribed to {len(self._tokens)} instrument(s).")

    def _on_error(self, websocket_connection, error):
        """
        Reports an error; Dhan refuses a login with a disconnect packet rather than at the handshake.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error.

        Returns:
            None: This method returns nothing.
        """
        self._logger.error(f"{self.name} error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Decodes a binary message into ticks and hands them on; text frames are ignored.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The message.

        Returns:
            None: This method returns nothing.
        """
        if not isinstance(message, bytes):
            return
        ticks = []
        for packet in self._split_packets(message):
            tick = self._parse_packet(packet)
            if tick:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)

    def _split_packets(self, message):
        """
        Splits a message into its packets, each of which declares its own length.

        Args:
            message (bytes): The binary message.

        Returns:
            list[bytes]: The packets, stopping at a packet that claims no length or more than is left.
        """
        packets = []
        offset = 0
        while offset + 8 <= len(message):
            length = self._unpack(message, offset + 1, offset + 3, "h")
            if length <= 0 or offset + length > len(message):
                break
            packets.append(message[offset:offset + length])
            offset = offset + length
        return packets

    def _parse_packet(self, packet):
        """
        Builds a normalized tick from one packet, remembering the single-value packets.

        Args:
            packet (bytes): The binary packet.

        Returns:
            dict | None: The tick, or None for a packet that carries no tick.
        """
        if len(packet) < 8:
            return None
        feed_code = self._unpack(packet, 0, 1, "B")
        segment_code = self._unpack(packet, 3, 4, "B")
        token = f"{SEGMENT_NAMES.get(segment_code, segment_code)}:{self._unpack(packet, 4, 8, 'i')}"

        if feed_code == DISCONNECT:
            code = None
            if len(packet) >= 10:
                code = self._unpack(packet, 8, 10, "h")
            self._logger.warning(f"{self.name} received a disconnect packet, code {code}.")
            if code in AUTHENTICATION_DISCONNECT_CODES:
                self._authentication_rejected = True
                self._websocket_application.close()
            return None

        remembered = self._remembered.setdefault(token, {})
        if feed_code == PREVIOUS_CLOSE and len(packet) >= 16:
            remembered["previous_close"] = self._unpack(packet, 8, 12, "f")
            return None
        if feed_code == OPEN_INTEREST and len(packet) >= 12:
            remembered["oi"] = self._unpack(packet, 8, 12, "i")
            return None

        if feed_code == TICKER and len(packet) >= 16:
            tick = self._empty_tick(token, segment_code, "ltp")
            tick["last_price"] = self._unpack(packet, 8, 12, "f")
            tick["last_trade_time"] = self._true_epoch(self._unpack(packet, 12, 16, "i"))
            return tick

        if feed_code == QUOTE and len(packet) >= 50:
            tick = self._empty_tick(token, segment_code, "quote")
            self._fill_trade(tick, packet)
            tick["ohlc"] = {
                "open": self._unpack(packet, 34, 38, "f"),
                "close": self._unpack(packet, 38, 42, "f"),
                "high": self._unpack(packet, 42, 46, "f"),
                "low": self._unpack(packet, 46, 50, "f"),
            }
            tick["oi"] = remembered.get("oi")
            self._apply_previous_close(tick, remembered)
            return tick

        if feed_code == FULL and len(packet) >= 162:
            tick = self._empty_tick(token, segment_code, "full")
            self._fill_trade(tick, packet)
            tick["oi"] = self._unpack(packet, 34, 38, "i")
            tick["oi_day_high"] = self._unpack(packet, 38, 42, "i")
            tick["oi_day_low"] = self._unpack(packet, 42, 46, "i")
            tick["ohlc"] = {
                "open": self._unpack(packet, 46, 50, "f"),
                "close": self._unpack(packet, 50, 54, "f"),
                "high": self._unpack(packet, 54, 58, "f"),
                "low": self._unpack(packet, 58, 62, "f"),
            }
            self._apply_previous_close(tick, remembered)
            for offset in range(62, 162, 20):
                tick["depth"]["buy"].append({
                    "quantity": self._unpack(packet, offset, offset + 4, "i"),
                    "price": self._unpack(packet, offset + 12, offset + 16, "f"),
                    "orders": self._unpack(packet, offset + 8, offset + 10, "h"),
                })
                tick["depth"]["sell"].append({
                    "quantity": self._unpack(packet, offset + 4, offset + 8, "i"),
                    "price": self._unpack(packet, offset + 16, offset + 20, "f"),
                    "orders": self._unpack(packet, offset + 10, offset + 12, "h"),
                })
            return tick

        self._logger.debug(f"{self.name} skipped a packet with feed code {feed_code} and length {len(packet)}.")
        return None

    def _fill_trade(self, tick, packet):
        """
        Fills the trade fields the quote and full packets share, at the same offsets.

        Args:
            tick (dict): The tick to fill.
            packet (bytes): The binary packet.

        Returns:
            None: This method returns nothing.
        """
        tick["last_price"] = self._unpack(packet, 8, 12, "f")
        tick["last_quantity"] = self._unpack(packet, 12, 14, "h")
        tick["last_trade_time"] = self._true_epoch(self._unpack(packet, 14, 18, "i"))
        tick["average_price"] = self._unpack(packet, 18, 22, "f")
        tick["volume"] = self._unpack(packet, 22, 26, "i")
        tick["sell_quantity"] = self._unpack(packet, 26, 30, "i")
        tick["buy_quantity"] = self._unpack(packet, 30, 34, "i")

    def _empty_tick(self, token, segment_code, mode):
        """
        A tick with every field unset.

        Args:
            token (str): The instrument's `SEGMENT:SECURITY_ID`.
            segment_code (int): Dhan's numeric segment.
            mode (str): `ltp`, `quote` or `full`.

        Returns:
            dict: The tick, named from the batch's names or by its token.
        """
        return {
            "id": self._names.get(token) or token,
            "broker": "dhan",
            "instrument_token": token,
            "exchange": SEGMENT_NAMES.get(segment_code),
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

    def _unpack(self, data, start, end, byte_format):
        """
        A little endian value from a slice of a packet.

        Args:
            data (bytes): The packet or message.
            start (int): Where the slice starts.
            end (int): Where the slice ends.
            byte_format (str): The `struct` format character.

        Returns:
            int | float: The value.
        """
        return struct.unpack("<" + byte_format, data[start:end])[0]

    def _true_epoch(self, timestamp):
        """
        A Dhan India-wall-clock-as-epoch timestamp on the true epoch.

        Args:
            timestamp (int): The timestamp Dhan sent.

        Returns:
            int | None: The true epoch, or None for zero.
        """
        if timestamp:
            return timestamp - IST_OFFSET_SECONDS
        return None

    def _apply_previous_close(self, tick, remembered):
        """
        Puts the previous session's close in `ohlc.close` once Dhan has sent it, and the change against it.

        Args:
            tick (dict): The tick to adjust.
            remembered (dict): What the instrument's single-value packets left.

        Returns:
            None: This method returns nothing.
        """
        if remembered.get("previous_close"):
            tick["ohlc"]["close"] = remembered["previous_close"]
        close = tick["ohlc"]["close"]
        if close:
            tick["change"] = (tick["last_price"] - close) * 100 / close
        else:
            tick["change"] = None


class DhanOrderUpdatesSocket(BrokerWebsocket):
    """
    Dhan's order update websocket, which logs in with a message after connecting.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (DhanSession): The login.
            on_updates (callable): Called on this socket's thread with each message's order alerts, as a list of `Data` dictionaries exactly as Dhan sent them, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates

    def _connect(self):
        """
        Opens the websocket and blocks until it closes; the login message is sent once it opens.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        self._websocket_application = websocket.WebSocketApp(
            ORDER_UPDATES_URL,
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
        Sends the login message with the token in force now.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        client_id, token = self._session.credentials()
        websocket_connection.send(json.dumps({
            "LoginReq": {
                "MsgCode": LOGIN_MESSAGE_CODE,
                "ClientId": str(client_id),
                "Token": token,
            },
            "UserType": "SELF",
        }))
        self._logger.info(f"{self.name} opened and logged in. Waiting for order updates.")

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
        Hands a message's order alerts on, and treats a binary frame as a refused login.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The frame: one JSON message, a JSON list of them, or Dhan's binary rejection.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            self._logger.warning(f"Dhan sent a binary frame, taken as a refused login: {bytes(message)[:80]!r}")
            self._authentication_rejected = True
            websocket_connection.close()
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
            if entry.get("Type") == ORDER_ALERT:
                orders.append(entry.get("Data"))
            else:
                self._logger.info(f"Ignoring a message of type {entry.get('Type')!r}: {json.dumps(entry)[:200]}")
        if orders:
            self._on_updates(orders, received_at)
