"""
Kotak's two websockets: the SFeed market feed that Kotak's own Python SDK (`kotakneoapi` 3.0) streams from, and the account's order and position update stream.

**The login.**
`KotakSession` holds the `KotakAPI` both sockets read the login from, afresh on every connect, so a login made by any process is picked up.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the session that failed; the order socket logs in again whenever it is refused, without that check, as it always has.

**Quotes.**
`KotakQuotesSocket` connects to the `feed_url` the login stored from Kotak's `feedUrl`, or to `wss://sfeed.kotaksecurities.com/apifeed` when the login has none.
Kotak retired the earlier HSM feed at `wss://mlhsm.kotaksecurities.com` in October 2026; it refuses connections.
Control messages are JSON text frames.
Once the socket opens it sends the `native_batch` authentication message, with the account's UCC as `user` and the session id as `auth`.
Kotak answers with message code 1119 and then 1117, both carrying each exchange's numeric id and price divider, and the first of them makes the socket subscribe every instrument once, with `subscribeDepth` and `ack_symbol`, in one message.
Kotak checks the session only after that: message code 1120 means it refused the session, and its text, which repeats the session id, is never logged.
Message code 1109 acknowledges the subscription and maps each `EXCHANGE|TOKEN` to its trading symbol, which names any instrument that had no name; binary frames that arrive before it are held back and decoded after it, so every instrument is named before its first tick.
Market data arrives in binary frames, each holding packets laid end to end in little-endian byte order.
A packet starts with its length in two bytes, then its message code, exchange id, level, auction flag, sequence number and bitmask length, nine bytes in all.
A market picture, at level 2, 4, 8 or 16, carries the instrument's whole state rather than a change: a fixed body of 135 bytes, then depth rows of 16 bytes, buy side first; `subscribeDepth` sends level 8, with five rows a side.
A packet is read as a market picture by its level, as `kotakneoapi` reads it, after the message codes that are something else are set aside: a closing auction update (104), a market status (105), the market opening and closing (6511 and 6521) and an index (7207); those, and any packet at another level or too short for the fixed body, are skipped.
Prices are integers divided by the exchange's divider, 100 on most exchanges and 10,000,000 on `cde_fo` and `bse_cd`; times are Unix seconds.
Within one frame only an instrument's latest market picture is handed on.
The quote socket gives up only after six more failed connects, not on the first refusal after logging in again.

**Order updates.**
`KotakOrderUpdatesSocket` connects to `wss://<host>/realtime`, where the host is the `base_url` Kotak assigned the session at login.
After connecting it sends Kotak's connection frame, a raw unquoted string that is deliberately not JSON: `{type:cn,Authorization:<access token>,Sid:<session id>,src:WEB}`.
Kotak acknowledges it with `{"ak":"ok","type":"cn",...}` or refuses it with `{"ak":"nk","type":"failed to connect","msg":...}`; a refusal discards whatever else the same message carried.
From then on the connection carries `{"type": "order", "data": {...}}` and `{"type": "position", "data": {...}}` messages with Kotak's abbreviated fields.

Neither socket writes Redis.
The quotes socket hands names to `on_name` and each data frame's ticks to `on_ticks`, and the order socket hands each message's orders and positions to `on_updates`; the scripts in `bin/kotak/` do the writing.
"""

import json
import struct
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

DEFAULT_FEED_URL = "wss://sfeed.kotaksecurities.com/apifeed"
REALTIME_PATH = "/realtime"

FEED_FORMAT = "native_batch"
FEED_SOURCE = "NEOTRADEAPI"
FEED_PLATFORM = "Web"
FEED_VERSION = "1.2.3"
FEED_SDK_VERSION = 2
FEED_SDK_DATE = "2026-08-07T09:41:17.667Z"
SUBSCRIBE_DEPTH_EVENT = "subscribeDepth"
SUBSCRIBED_DESCRIPTION = "SUBSCRIBED"

AUTHENTICATION_ANSWER_CODES = (
    1117,
    1119,
)
AUTHENTICATION_REFUSED_CODE = 1120
SUBSCRIPTION_ACKNOWLEDGEMENT_CODE = 1109

PACKET_LENGTH = struct.Struct("<H")
PACKET_HEADER = struct.Struct("<HHbBBBB")
MARKET_PICTURE = struct.Struct("<IqqqqqIIIIIqIIIIhiIdiIIIIIBI")
DEPTH_ROW = struct.Struct("<qii")
MARKET_PICTURE_END = PACKET_HEADER.size + MARKET_PICTURE.size
MARKET_PICTURE_LEVELS = (
    2,
    4,
    8,
    16,
)
NOT_MARKET_PICTURE_CODES = (
    104,
    105,
    6511,
    6521,
    7207,
)
TOUCH_LINE_LEVEL = 4
DEFAULT_DIVIDER = 100
MAX_HELD_FRAMES = 1000

EXCHANGE_NAMES = {
    1: "nse_cm",
    2: "nse_fo",
    3: "cde_fo",
    4: "nse_com",
    5: "bse_cm",
    6: "bse_fo",
    7: "bse_cd",
    8: "bse_co",
    9: "mcx_fo",
    10: "ncd_co",
}

ORDER = "order"
POSITION = "position"
CONNECT_ACK = "cn"

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class KotakFeedRequests:
    """
    Builds the JSON control messages a client sends to Kotak's SFeed market feed.
    """

    def authentication(self, ucc, session_id, requested_at_milliseconds):
        """
        Builds the `native_batch` authentication message, as `kotakneoapi` 3.0.9 sends it.

        Args:
            ucc (str): The account's unique client code.
            session_id (str): The session id from Kotak's login.
            requested_at_milliseconds (int): The time of the request in Unix milliseconds.

        Returns:
            str: The message.
        """
        return json.dumps({
            "user": ucc,
            "auth": session_id,
            "format": FEED_FORMAT,
            "source": FEED_SOURCE,
            "platform": FEED_PLATFORM,
            "version": FEED_VERSION,
            "sdk_version": FEED_SDK_VERSION,
            "sdk_date": FEED_SDK_DATE,
            "conn_req_time": requested_at_milliseconds,
            "sessionValidation": False,
        })

    def subscription(self, instrument_tokens):
        """
        Builds one subscription to every instrument's five-level depth, asking for their trading symbols.

        Args:
            instrument_tokens (list[str]): The `EXCHANGE|TOKEN` instruments.

        Returns:
            str: The message.
        """
        return json.dumps({
            "event": SUBSCRIBE_DEPTH_EVENT,
            "inputtoken": ",".join(instrument_tokens),
            "ack_symbol": True,
        })


class KotakFeedDecoder:
    """
    Splits SFeed's binary frames into packets and turns market pictures into normalized ticks.
    """

    def __init__(self):
        """
        Starts with no exchanges learned, so every exchange uses the static names and the default divider.

        Returns:
            None: This method returns nothing.
        """
        self._names = dict(EXCHANGE_NAMES)
        self._dividers = {}

    def learn_exchanges(self, exchanges):
        """
        Takes the exchange ids and price dividers from Kotak's answer to the authentication message.

        Args:
            exchanges (dict): Exchange names to `{"value": id, "divider": divider}`, as Kotak sends them.

        Returns:
            None: This method returns nothing.
        """
        for name, details in exchanges.items():
            if not isinstance(details, dict) or details.get("value") is None:
                continue
            exchange_id = int(details["value"])
            self._names[exchange_id] = name
            self._dividers[exchange_id] = details.get("divider") or DEFAULT_DIVIDER

    def packets(self, frame):
        """
        Splits a binary frame into its packets, stopping at a length that is too short or runs past the frame.

        Args:
            frame (bytes): The frame.

        Returns:
            list[bytes]: The whole packets, in order.
        """
        packets = []
        offset = 0
        while offset + PACKET_LENGTH.size <= len(frame):
            size = PACKET_LENGTH.unpack_from(frame, offset)[0]
            if size < PACKET_HEADER.size or offset + size > len(frame):
                break
            packets.append(frame[offset:offset + size])
            offset = offset + size
        return packets

    def tick(self, packet, names):
        """
        Builds the normalized tick a market picture carries.

        Args:
            packet (bytes): One packet.
            names (dict[str, str]): `EXCHANGE|TOKEN` to trading symbol.

        Returns:
            dict | None: The tick, or None when the packet is not a whole market picture.
        """
        _, message_code, exchange_id, level, _, _, _ = PACKET_HEADER.unpack_from(packet, 0)
        if message_code in NOT_MARKET_PICTURE_CODES:
            return None
        if level not in MARKET_PICTURE_LEVELS or len(packet) < MARKET_PICTURE_END:
            return None
        (
            token,
            buy_quantity,
            sell_quantity,
            volume,
            last_trade_time,
            exchange_timestamp,
            open_price,
            close_price,
            high_price,
            low_price,
            last_price,
            last_quantity,
            average_price,
            _,
            buy_rows,
            sell_rows,
            _,
            _,
            open_interest,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
            _,
        ) = MARKET_PICTURE.unpack_from(packet, PACKET_HEADER.size)
        divider = self._dividers.get(exchange_id) or DEFAULT_DIVIDER
        exchange = self._names.get(exchange_id, str(exchange_id))
        instrument_token = f"{exchange}|{token}"
        if level == TOUCH_LINE_LEVEL:
            buy_rows = 1
            sell_rows = 1
        buy_levels, sell_levels = self._depth(packet, buy_rows, sell_rows, divider)
        last = last_price / divider
        close = close_price / divider
        change = None
        if close:
            change = (last - close) * 100 / close
        mode = "quote"
        if buy_levels or sell_levels:
            mode = "full"
        return {
            "id": names.get(instrument_token) or instrument_token,
            "broker": "kotak",
            "instrument_token": instrument_token,
            "exchange": exchange,
            "mode": mode,
            "last_price": last,
            "last_quantity": last_quantity,
            "average_price": average_price / divider,
            "volume": volume,
            "buy_quantity": buy_quantity,
            "sell_quantity": sell_quantity,
            "ohlc": {
                "open": open_price / divider,
                "high": high_price / divider,
                "low": low_price / divider,
                "close": close,
            },
            "change": change,
            "oi": open_interest,
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": last_trade_time if last_trade_time > 0 else None,
            "exchange_timestamp": exchange_timestamp if exchange_timestamp > 0 else None,
            "depth": {
                "buy": buy_levels,
                "sell": sell_levels,
            },
            "received_at": time.time(),
        }

    def _depth(self, packet, buy_rows, sell_rows, divider):
        """
        Reads a market picture's depth rows, as many as the packet holds of those it declares.

        Args:
            packet (bytes): The market picture.
            buy_rows (int): How many buy rows it declares.
            sell_rows (int): How many sell rows it declares, after the buy rows.
            divider (int): The exchange's price divider.

        Returns:
            tuple: The buy levels and the sell levels, each a list of `{quantity, price, orders}`, best first.
        """
        buy_levels = []
        sell_levels = []
        offset = MARKET_PICTURE_END
        for row in range(buy_rows + sell_rows):
            if offset + DEPTH_ROW.size > len(packet):
                break
            quantity, price, orders = DEPTH_ROW.unpack_from(packet, offset)
            level = {
                "quantity": quantity,
                "price": price / divider,
                "orders": orders,
            }
            if row < buy_rows:
                buy_levels.append(level)
            else:
                sell_levels.append(level)
            offset = offset + DEPTH_ROW.size
        return buy_levels, sell_levels


class KotakSession:
    """
    The Kotak login every socket authenticates with, logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `KotakAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `KotakAPI` raises when it cannot log in.
        """
        from stock_brokers.api.kotak import KotakAPI

        self._api_class = KotakAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._kotak = KotakAPI()

    def current_login(self):
        """
        The stored login in force now, which may be one another process has just obtained.

        Returns:
            dict: The login, with `access_token`, `sid`, `base_url` and `feed_url` among its fields; empty when none is stored.
        """
        return self._kotak._current_login() or {}

    def credentials(self):
        """
        The access token and session id in force now.

        Returns:
            tuple: The access token and the session id, either of which may be None.
        """
        login = self.current_login()
        return login.get("access_token"), login.get("sid")

    def feed_credentials(self):
        """
        The UCC and session id the market feed authenticates with.

        Returns:
            tuple: The account's UCC from Kotak's settings and the session id in force now, either of which may be None.
        """
        settings = self._kotak._settings or {}
        return settings.get("ucc_code"), self.current_login().get("sid")

    def feed_url(self):
        """
        The market feed's address for the login in force now.

        Returns:
            str: The `feed_url` the login stored, or Kotak's default address when it stored none.
        """
        return self.current_login().get("feed_url") or DEFAULT_FEED_URL

    def log_in_again(self, stale_session_id):
        """
        Logs in again, unless another socket or process already replaced the session that failed.

        Args:
            stale_session_id (str | None): The session id the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `KotakAPI` raises when it cannot log in.
        """
        with self._lock:
            if self.credentials()[1] != stale_session_id:
                return
            self._log_in()

    def log_in_again_without_checking(self):
        """
        Logs in again whether or not the session was already replaced.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `KotakAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `KotakAPI` again; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `KotakAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Kotak again.")
        self._kotak = self._api_class()


class KotakQuotesSocket(BrokerWebsocket):
    """
    One Kotak SFeed websocket carrying the five-level depth of a batch of instruments.
    """

    def __init__(self, name, instrument_tokens, names, session, on_name, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            instrument_tokens (list[str]): The batch of `EXCHANGE|TOKEN` instruments.
            names (dict[str, str]): `EXCHANGE|TOKEN` to trading symbol, shared by every socket and added to as the subscription acknowledgement names instruments.
            session (KotakSession): The shared login.
            on_name (callable): Called with an instrument and its trading symbol when the acknowledgement names an unnamed instrument, on this socket's thread.
            on_ticks (callable): Called with each data frame's ticks, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._instrument_tokens = instrument_tokens
        self._names = names
        self._session = session
        self._on_name = on_name
        self._on_ticks = on_ticks
        self._requests = KotakFeedRequests()
        self._decoder = KotakFeedDecoder()
        self._session_id = None
        self._subscribed = False
        self._acknowledged = False
        self._held_frames = []

    def _gives_up_after_logging_in_again(self, failed_connects):
        """
        Gives up only once six connects in a row have failed, as Kotak's quotes loop always has.

        Args:
            failed_connects (int): How many connects in a row have failed since the last login.

        Returns:
            bool: True to give up now.
        """
        return failed_connects >= self.MAX_FAILED_CONNECTS

    def _connect(self):
        """
        Opens the websocket at the feed address in force now and blocks until it closes; the authentication is sent once it opens.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        self._websocket_application = websocket.WebSocketApp(
            self._session.feed_url(),
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
        Logs in again through the shared session, which skips the login when the session was already replaced.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again(self._session_id)

    def _on_open(self, websocket_connection):
        """
        Sends the authentication with the login in force now; subscribing waits for Kotak's answer.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._decoder = KotakFeedDecoder()
        self._subscribed = False
        self._acknowledged = False
        self._held_frames = []
        ucc, self._session_id = self._session.feed_credentials()
        if not ucc or not self._session_id:
            self._logger.error(f"{self.name}: no Kotak UCC or session id is stored.")
            self._authentication_rejected = True
            websocket_connection.close()
            return
        websocket_connection.send(self._requests.authentication(ucc, self._session_id, int(time.time() * 1000)))
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
        self._logger.error(f"{self.name} error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Handles a JSON control message, or decodes a binary frame, holding binary frames back until the subscription is acknowledged.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, str):
            self._handle_control(websocket_connection, message)
            return
        frame = bytes(message)
        if self._acknowledged:
            self._hand_on_ticks(frame)
            return
        self._held_frames.append(frame)
        if len(self._held_frames) >= MAX_HELD_FRAMES:
            self._logger.warning(f"{self.name}: Kotak has not acknowledged the subscription after {len(self._held_frames)} data frames; decoding them without its names.")
            self._release_held_frames()

    def _handle_control(self, websocket_connection, text):
        """
        Acts on one JSON control message by its message code.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection.
            text (str): The message.

        Returns:
            None: This method returns nothing.
        """
        try:
            message = json.loads(text)
        except ValueError:
            self._logger.info(f"{self.name} ignored a text frame that is not JSON.")
            return
        if not isinstance(message, dict):
            self._logger.info(f"{self.name} ignored a text frame that is not a JSON object.")
            return
        message_code = message.get("message_code")
        if message_code in AUTHENTICATION_ANSWER_CODES:
            self._decoder.learn_exchanges(message.get("exchanges") or {})
            if not self._subscribed:
                self._subscribe(websocket_connection)
        elif message_code == SUBSCRIPTION_ACKNOWLEDGEMENT_CODE:
            self._handle_acknowledgement(message)
        elif message_code == AUTHENTICATION_REFUSED_CODE:
            self._logger.error(f"{self.name}: Kotak refused the session (message code {message_code}).")
            self._authentication_rejected = True
            websocket_connection.close()
        else:
            self._logger.info(f"{self.name} ignored a control message with message code {message_code}.")

    def _subscribe(self, websocket_connection):
        """
        Subscribes every instrument's five-level depth in one message.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection Kotak answered on.

        Returns:
            None: This method returns nothing.
        """
        websocket_connection.send(self._requests.subscription(self._instrument_tokens))
        self._subscribed = True
        self._logger.info(f"{self.name} authenticated and subscribed to {len(self._instrument_tokens)} instrument(s) with depth.")

    def _handle_acknowledgement(self, message):
        """
        Reports a refused subscription, names the instruments the acknowledgement names, and decodes the frames held back for it.

        Args:
            message (dict): The acknowledgement.

        Returns:
            None: This method returns nothing.
        """
        description = message.get("description")
        error_code = message.get("error_code")
        if description != SUBSCRIBED_DESCRIPTION or error_code:
            self._logger.error(f"{self.name}: Kotak answered the subscription with {description!r} (error code {error_code}).")
        trading_symbols = message.get("trading_symbols")
        if isinstance(trading_symbols, dict):
            for instrument_token, trading_symbol in trading_symbols.items():
                if trading_symbol and not self._names.get(instrument_token):
                    self._names[instrument_token] = trading_symbol
                    self._on_name(instrument_token, trading_symbol)
        self._release_held_frames()

    def _release_held_frames(self):
        """
        Stops holding frames back and decodes the ones already held, in arrival order.

        Returns:
            None: This method returns nothing.
        """
        self._acknowledged = True
        held_frames = self._held_frames
        self._held_frames = []
        for frame in held_frames:
            self._hand_on_ticks(frame)

    def _hand_on_ticks(self, frame):
        """
        Hands on the latest tick of each instrument a binary frame carries a market picture for.

        Args:
            frame (bytes): The frame.

        Returns:
            None: This method returns nothing.
        """
        latest = {}
        for packet in self._decoder.packets(frame):
            tick = self._decoder.tick(packet, self._names)
            if tick is not None:
                latest[tick["instrument_token"]] = tick
        if latest:
            self._on_ticks(list(latest.values()))


class KotakOrderUpdatesSocket(BrokerWebsocket):
    """
    Kotak's order and position update websocket, on the host the session was assigned.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (KotakSession): The login.
            on_updates (callable): Called on this socket's thread with a message's order and position `data` objects, exactly as Kotak sent them, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates

    def _connect(self):
        """
        Opens the websocket on the session's own host and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the stored login has no host.
        """
        import websocket

        base_url = self._session.current_login().get("base_url")
        if not base_url or base_url == "None":
            raise RuntimeError("the stored Kotak login has no base_url, so there is no order update host")
        host = str(base_url).split("://", 1)[-1].strip("/")
        self._websocket_application = websocket.WebSocketApp(
            f"wss://{host}{REALTIME_PATH}",
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
        Logs in again, without checking whether another process already replaced the session.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Sends the raw connection frame with the token and session id in force now.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        access_token, session_id = self._session.credentials()
        websocket_connection.send(f"{{type:cn,Authorization:{access_token},Sid:{session_id},src:WEB}}")
        self._logger.info(f"{self.name} opened. Waiting for Kotak's acknowledgement.")

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
        Hands a message's orders and positions on, and treats a refused connection frame as a dead session.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The message: one JSON object or a JSON list of them.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            message = bytes(message).decode("utf-8", errors="replace")
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
        positions = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            message_type = entry.get("type")
            if entry.get("ak") == "nk" or message_type == "failed to connect":
                self._logger.error(f"Kotak refused the order update connection: {entry.get('msg') or entry}")
                self._authentication_rejected = True
                websocket_connection.close()
                return
            if message_type == CONNECT_ACK or entry.get("ak") == "ok":
                self._logger.info(f"{self.name} authenticated. Waiting for updates.")
            elif message_type == ORDER:
                orders.append(entry.get("data"))
            elif message_type == POSITION:
                positions.append(entry.get("data"))
            else:
                self._logger.info(f"Ignoring a message of type {message_type!r}: {json.dumps(entry)[:200]}")
        if orders or positions:
            self._on_updates(orders, positions, received_at)
