"""
Kotak's two websockets: the HSM market feed that Kotak's own Python SDK (`neo_api_client`) streams from, and the account's order and position update stream.

**The login.**
`KotakSession` holds the `KotakAPI` both sockets read the access token, the session id and the account's host from, afresh on every connect, so a login made by any process is picked up.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the session that failed; the order socket logs in again whenever it is refused, without that check, as it always has.

**Quotes.**
`KotakQuotesSocket` connects to `wss://mlhsm.kotaksecurities.com`.
Every request and response is a binary frame that begins with its length in two big-endian bytes and then a one-byte frame type.
The connection request (type 1) carries the access token, the session id and the source `JS_API` as length-prefixed fields.
Kotak answers with a type 1 frame whose status is `K` for accepted, and with the number of data frames after which it wants an acknowledgement.
Every instrument is subscribed twice, as a scrip topic (`sf|EXCHANGE|TOKEN`) for its prices and quantities and as a depth topic (`dp|EXCHANGE|TOKEN`) for its five-level book, up to 100 topics a subscription request (type 4) on channel 1.
Data frames (type 6) begin with a four-byte message number when acknowledgements were asked for, and after that many data frames the socket sends an acknowledgement (type 3) carrying the last message number.
Each data frame holds packets that are either a snapshot (`S`, 83) - topic id, topic name, the numeric fields as four-byte signed integers in field order, and string fields by id - or an update (`U`, 85) - topic id and the numeric fields again, where -2147483648 means unchanged.
A topic's latest values are kept, and a whole tick is built for an instrument every time either of its topics changes, once its scrip snapshot has arrived.
A snapshot's trading symbol (string field 54) names an instrument that had no name, and that name is handed to `on_name` before the frame's ticks.
Prices are integers divided by the topic's multiplier (scrip field 23, depth field 32) times ten to its precision (scrip field 24, depth field 33).
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
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://mlhsm.kotaksecurities.com"
REALTIME_PATH = "/realtime"

CONNECTION_SOURCE = "JS_API"
CONNECTION_FRAME = 1
ACKNOWLEDGEMENT_FRAME = 3
SUBSCRIBE_FRAME = 4
DATA_FRAME = 6
SNAPSHOT_PACKET = 83
UPDATE_PACKET = 85
STATUS_ACCEPTED = "K"
UNCHANGED_VALUE = -2147483648
CHANNEL_NUMBER = 1
MAX_TOPICS_PER_REQUEST = 100

SCRIP_TOPIC = "sf"
DEPTH_TOPIC = "dp"

SCRIP_EXCHANGE_TIMESTAMP = 2
SCRIP_LAST_TRADE_TIME = 3
SCRIP_VOLUME = 4
SCRIP_LAST_PRICE = 5
SCRIP_LAST_QUANTITY = 6
SCRIP_BUY_QUANTITY = 7
SCRIP_SELL_QUANTITY = 8
SCRIP_AVERAGE_PRICE = 13
SCRIP_LOW = 14
SCRIP_HIGH = 15
SCRIP_OPEN = 20
SCRIP_CLOSE = 21
SCRIP_OPEN_INTEREST = 22
SCRIP_MULTIPLIER = 23
SCRIP_PRECISION = 24

DEPTH_LEVELS = 5
DEPTH_BUY_PRICE = 2
DEPTH_SELL_PRICE = 7
DEPTH_BUY_QUANTITY = 12
DEPTH_SELL_QUANTITY = 17
DEPTH_BUY_ORDERS = 22
DEPTH_SELL_ORDERS = 27
DEPTH_MULTIPLIER = 32
DEPTH_PRECISION = 33

STRING_TRADING_SYMBOL = 54

ORDER = "order"
POSITION = "position"
CONNECT_ACK = "cn"

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class KotakTruncatedFrameError(ValueError):
    """A binary frame ended before a field it declared."""


class KotakFrameReader:
    """
    A cursor over one binary frame from Kotak's HSM feed, reading big-endian fields in order.

    Attributes:
        position (int): The offset of the next unread byte.
    """

    def __init__(self, data):
        """
        Starts reading a frame at its first byte.

        Args:
            data (bytes): The binary frame.

        Returns:
            None: This method returns nothing.
        """
        self._data = data
        self.position = 0

    def _take(self, size):
        """
        The next bytes, moving past them.

        Args:
            size (int): How many bytes to read.

        Returns:
            bytes: The bytes read.

        Raises:
            KotakTruncatedFrameError: The frame has fewer than `size` bytes left.
        """
        end = self.position + size
        if end > len(self._data):
            raise KotakTruncatedFrameError(f"frame of {len(self._data)} bytes ended reading {size} at {self.position}")
        chunk = self._data[self.position:end]
        self.position = end
        return chunk

    def read_unsigned(self, size):
        """
        Reads an unsigned big-endian integer.

        Args:
            size (int): Its width in bytes.

        Returns:
            int: The integer.

        Raises:
            KotakTruncatedFrameError: The frame ends first.
        """
        return int.from_bytes(self._take(size), "big")

    def read_signed_integer(self):
        """
        Reads a four-byte signed big-endian integer.

        Returns:
            int: The integer.

        Raises:
            KotakTruncatedFrameError: The frame ends first.
        """
        return int.from_bytes(self._take(4), "big", signed=True)

    def read_text(self, size):
        """
        Reads a string of single-byte characters.

        Args:
            size (int): Its length in bytes.

        Returns:
            str: The string.

        Raises:
            KotakTruncatedFrameError: The frame ends first.
        """
        return self._take(size).decode("latin-1")


class KotakFeedRequests:
    """
    Builds the binary requests a client sends to Kotak's HSM feed.
    """

    def connection(self, access_token, session_id):
        """
        Builds the connection request.

        Args:
            access_token (str): The REST access token from Kotak's login.
            session_id (str): The session id from Kotak's login.

        Returns:
            bytes: The frame.
        """
        fields = [
            self._field(1, access_token.encode("latin-1")),
            self._field(2, session_id.encode("latin-1")),
            self._field(3, CONNECTION_SOURCE.encode("latin-1")),
        ]
        return self._framed(CONNECTION_FRAME, fields)

    def subscription(self, topic_prefix, instrument_tokens):
        """
        Builds a subscription to up to 100 topics on channel 1.

        Args:
            topic_prefix (str): `sf` or `dp`.
            instrument_tokens (list[str]): The `EXCHANGE|TOKEN` instruments.

        Returns:
            bytes: The frame.
        """
        names = bytearray(len(instrument_tokens).to_bytes(2, "big"))
        for instrument_token in instrument_tokens:
            topic_name = f"{topic_prefix}|{instrument_token}".encode("latin-1")
            names.append(len(topic_name))
            names.extend(topic_name)
        fields = [
            self._field(1, bytes(names)),
            self._field(2, bytes([CHANNEL_NUMBER])),
        ]
        return self._framed(SUBSCRIBE_FRAME, fields)

    def acknowledgement(self, message_number):
        """
        Builds the acknowledgement of data frames up to a message number.

        Args:
            message_number (int): The message number of the last data frame received.

        Returns:
            bytes: The frame.
        """
        fields = [
            self._field(1, message_number.to_bytes(4, "big", signed=True)),
        ]
        return self._framed(ACKNOWLEDGEMENT_FRAME, fields)

    def _framed(self, frame_type, fields):
        """
        Joins a frame type and its fields behind the frame's length.

        Args:
            frame_type (int): The frame type byte.
            fields (list[bytes]): The encoded fields, each already carrying its id and length.

        Returns:
            bytes: The whole frame.
        """
        body = bytes([frame_type, len(fields)]) + b"".join(fields)
        return len(body).to_bytes(2, "big") + body

    def _field(self, field_id, value):
        """
        Encodes one field as its id, a two-byte length and its bytes.

        Args:
            field_id (int): The field id.
            value (bytes): The field's value.

        Returns:
            bytes: The encoded field.
        """
        return bytes([field_id]) + len(value).to_bytes(2, "big") + value


class KotakFeedTopic:
    """
    The latest values of one subscribed topic, a scrip or a depth topic of one instrument.

    Attributes:
        kind (str): `sf` or `dp`.
        instrument_token (str): The instrument's `EXCHANGE|TOKEN`.
        strings (dict[int, str]): The topic's string fields by field id, such as its trading symbol.
    """

    def __init__(self, kind, instrument_token, strings):
        """
        Creates a topic from its snapshot's name and strings.

        Args:
            kind (str): `sf` or `dp`.
            instrument_token (str): The instrument's `EXCHANGE|TOKEN`.
            strings (dict[int, str]): The snapshot's string fields by field id.

        Returns:
            None: This method returns nothing.
        """
        self.kind = kind
        self.instrument_token = instrument_token
        self.strings = strings
        self._numbers = {}

    def apply(self, numbers):
        """
        Takes a snapshot's or an update's numeric fields, keeping earlier values where a field is unchanged.

        Args:
            numbers (list[int]): The numeric fields in field order.

        Returns:
            None: This method returns nothing.
        """
        for index, value in enumerate(numbers):
            if value != UNCHANGED_VALUE:
                self._numbers[index] = value

    def number(self, index):
        """
        A numeric field as sent.

        Args:
            index (int): The field index.

        Returns:
            int | None: The value, or None when the feed has not sent the field.
        """
        return self._numbers.get(index)

    def price(self, index):
        """
        A price field in rupees, scaled by the topic's multiplier and precision.

        Args:
            index (int): The field index.

        Returns:
            float | None: The price, or None when the feed has not sent the field.
        """
        value = self._numbers.get(index)
        if value is None:
            return None
        if self.kind == SCRIP_TOPIC:
            multiplier = self._numbers.get(SCRIP_MULTIPLIER) or 1
            precision = self._numbers.get(SCRIP_PRECISION, 2)
        else:
            multiplier = self._numbers.get(DEPTH_MULTIPLIER) or 1
            precision = self._numbers.get(DEPTH_PRECISION, 2)
        return round(value / (multiplier * 10 ** precision), precision)


class KotakInstrumentQuote:
    """
    One instrument's scrip and depth topics, turned into a normalized tick.

    Attributes:
        instrument_token (str): The instrument's `EXCHANGE|TOKEN`.
        scrip (KotakFeedTopic | None): The scrip topic, or None before its snapshot.
        depth (KotakFeedTopic | None): The depth topic, or None before its snapshot.
    """

    def __init__(self, instrument_token):
        """
        Creates an instrument with neither topic yet.

        Args:
            instrument_token (str): The instrument's `EXCHANGE|TOKEN`.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_token = instrument_token
        self.scrip = None
        self.depth = None

    def tick(self, name):
        """
        Builds the normalized tick from the latest topic values.

        Args:
            name (str | None): The instrument's trading symbol, or None when it has none.

        Returns:
            dict | None: The tick, or None before the scrip snapshot has arrived.
        """
        scrip = self.scrip
        if scrip is None:
            return None
        last_price = scrip.price(SCRIP_LAST_PRICE)
        close = scrip.price(SCRIP_CLOSE)
        change = None
        if last_price is not None and close:
            change = (last_price - close) * 100 / close
        buy_levels = self._depth_side(DEPTH_BUY_PRICE, DEPTH_BUY_QUANTITY, DEPTH_BUY_ORDERS)
        sell_levels = self._depth_side(DEPTH_SELL_PRICE, DEPTH_SELL_QUANTITY, DEPTH_SELL_ORDERS)
        mode = "quote"
        if buy_levels or sell_levels:
            mode = "full"
        return {
            "id": name or self.instrument_token,
            "broker": "kotak",
            "instrument_token": self.instrument_token,
            "exchange": self.instrument_token.partition("|")[0],
            "mode": mode,
            "last_price": last_price,
            "last_quantity": scrip.number(SCRIP_LAST_QUANTITY),
            "average_price": scrip.price(SCRIP_AVERAGE_PRICE),
            "volume": scrip.number(SCRIP_VOLUME),
            "buy_quantity": scrip.number(SCRIP_BUY_QUANTITY),
            "sell_quantity": scrip.number(SCRIP_SELL_QUANTITY),
            "ohlc": {
                "open": scrip.price(SCRIP_OPEN),
                "high": scrip.price(SCRIP_HIGH),
                "low": scrip.price(SCRIP_LOW),
                "close": close,
            },
            "change": change,
            "oi": scrip.number(SCRIP_OPEN_INTEREST),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": scrip.number(SCRIP_LAST_TRADE_TIME) or None,
            "exchange_timestamp": scrip.number(SCRIP_EXCHANGE_TIMESTAMP) or None,
            "depth": {
                "buy": buy_levels,
                "sell": sell_levels,
            },
            "received_at": time.time(),
        }

    def _depth_side(self, price_start, quantity_start, orders_start):
        """
        One side of the order book.

        Args:
            price_start (int): The field index of the best level's price.
            quantity_start (int): The field index of the best level's quantity.
            orders_start (int): The field index of the best level's order count.

        Returns:
            list[dict]: Up to five levels of `{quantity, price, orders}`, best first.
        """
        levels = []
        if self.depth is None:
            return levels
        for level in range(DEPTH_LEVELS):
            price = self.depth.price(price_start + level)
            quantity = self.depth.number(quantity_start + level)
            if price is None and quantity is None:
                continue
            levels.append({
                "quantity": quantity,
                "price": price,
                "orders": self.depth.number(orders_start + level),
            })
        return levels


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
            dict: The login, with `access_token`, `sid` and `base_url` among its fields; empty when none is stored.
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
    One Kotak HSM feed websocket carrying the scrip and depth topics of a batch of instruments.
    """

    def __init__(self, name, instrument_tokens, names, session, on_name, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            instrument_tokens (list[str]): The batch of `EXCHANGE|TOKEN` instruments.
            names (dict[str, str]): `EXCHANGE|TOKEN` to trading symbol, shared by every socket and added to as snapshots name instruments.
            session (KotakSession): The shared login.
            on_name (callable): Called with an instrument and its trading symbol when a snapshot names an unnamed instrument, on this socket's thread.
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
        self._session_id = None
        self._topics = {}
        self._quotes = {}
        self._acknowledge_every = 0
        self._frames_since_acknowledgement = 0

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
        Opens the websocket and blocks until it closes; the credentials are sent once it opens.

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

    def _send_binary(self, websocket_connection, frame):
        """
        Sends one binary frame.

        Args:
            websocket_connection (websocket.WebSocketApp): The open connection.
            frame (bytes): The frame.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        websocket_connection.send(frame, opcode=websocket.ABNF.OPCODE_BINARY)

    def _on_open(self, websocket_connection):
        """
        Sends the connection request with the login in force now; subscribing waits for Kotak's acceptance.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        self._topics = {}
        self._quotes = {}
        self._acknowledge_every = 0
        self._frames_since_acknowledgement = 0
        access_token, self._session_id = self._session.credentials()
        if not access_token or not self._session_id:
            self._logger.error(f"{self.name}: no Kotak access token or session id is stored.")
            self._authentication_rejected = True
            websocket_connection.close()
            return
        self._send_binary(websocket_connection, self._requests.connection(access_token, self._session_id))
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
        Dispatches a binary frame by its type.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, str):
            self._logger.info(f"{self.name} text frame: {message[:200]}")
            return
        data = bytes(message)
        if len(data) < 3:
            return
        reader = KotakFrameReader(data)
        reader.read_unsigned(2)
        frame_type = reader.read_unsigned(1)
        try:
            if frame_type == CONNECTION_FRAME:
                self._handle_connection(websocket_connection, reader)
            elif frame_type == SUBSCRIBE_FRAME:
                self._handle_subscription(reader)
            elif frame_type == DATA_FRAME:
                self._handle_data(websocket_connection, reader)
        except KotakTruncatedFrameError as error:
            self._logger.warning(f"{self.name} skipped the rest of a truncated frame of type {frame_type}: {error}")

    def _handle_connection(self, websocket_connection, reader):
        """
        Reads the connection response, then subscribes or reports the refusal.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection.
            reader (KotakFrameReader): The frame, positioned after its type.

        Returns:
            None: This method returns nothing.

        Raises:
            KotakTruncatedFrameError: The frame ends before a declared field.
        """
        field_count = reader.read_unsigned(1)
        status = None
        if field_count >= 1:
            reader.read_unsigned(1)
            status = reader.read_text(reader.read_unsigned(2))
        if field_count >= 2:
            reader.read_unsigned(1)
            self._acknowledge_every = reader.read_unsigned(reader.read_unsigned(2))
        if status != STATUS_ACCEPTED:
            self._logger.error(f"{self.name}: Kotak refused the session (status {status!r}).")
            self._authentication_rejected = True
            websocket_connection.close()
            return
        self._subscribe(websocket_connection)

    def _subscribe(self, websocket_connection):
        """
        Subscribes every instrument's scrip and depth topics, 100 at a time.

        Args:
            websocket_connection (websocket.WebSocketApp): The accepted connection.

        Returns:
            None: This method returns nothing.
        """
        for topic_prefix in (SCRIP_TOPIC, DEPTH_TOPIC):
            for start in range(0, len(self._instrument_tokens), MAX_TOPICS_PER_REQUEST):
                batch = self._instrument_tokens[start:start + MAX_TOPICS_PER_REQUEST]
                self._send_binary(websocket_connection, self._requests.subscription(topic_prefix, batch))
        self._logger.info(f"{self.name} authenticated and subscribed to {len(self._instrument_tokens)} instrument(s) with depth, acknowledging every {self._acknowledge_every} data frame(s).")

    def _handle_subscription(self, reader):
        """
        Reads a subscription response and reports a refusal.

        Args:
            reader (KotakFrameReader): The frame, positioned after its type.

        Returns:
            None: This method returns nothing.

        Raises:
            KotakTruncatedFrameError: The frame ends before a declared field.
        """
        field_count = reader.read_unsigned(1)
        if field_count < 1:
            return
        reader.read_unsigned(1)
        status = reader.read_text(reader.read_unsigned(2))
        if status != STATUS_ACCEPTED:
            self._logger.error(f"{self.name}: Kotak refused a subscription (status {status!r}).")

    def _handle_data(self, websocket_connection, reader):
        """
        Acknowledges data frames when asked, applies each packet to its topic, and hands on the changed instruments' ticks, even when the frame is cut short.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection.
            reader (KotakFrameReader): The frame, positioned after its type.

        Returns:
            None: This method returns nothing.

        Raises:
            KotakTruncatedFrameError: The frame ends before a declared field.
        """
        if self._acknowledge_every > 0:
            message_number = reader.read_signed_integer()
            self._frames_since_acknowledgement = self._frames_since_acknowledgement + 1
            if self._frames_since_acknowledgement >= self._acknowledge_every:
                self._send_binary(websocket_connection, self._requests.acknowledgement(message_number))
                self._frames_since_acknowledgement = 0

        changed_tokens = []
        try:
            packet_count = reader.read_unsigned(2)
            for _ in range(packet_count):
                reader.read_unsigned(2)
                packet_type = reader.read_unsigned(1)
                if packet_type == SNAPSHOT_PACKET:
                    topic = self._read_snapshot(reader)
                elif packet_type == UPDATE_PACKET:
                    topic = self._read_update(reader)
                else:
                    self._logger.warning(f"{self.name} stopped reading a frame at unknown packet type {packet_type}.")
                    break
                if topic is not None and topic.instrument_token not in changed_tokens:
                    changed_tokens.append(topic.instrument_token)
        finally:
            self._hand_on_ticks(changed_tokens)

    def _read_snapshot(self, reader):
        """
        Reads a snapshot packet and registers its topic, naming its instrument when it had no name.

        Args:
            reader (KotakFrameReader): The frame, positioned after the packet type.

        Returns:
            KotakFeedTopic | None: The topic, or None when its name is not a scrip or depth topic.

        Raises:
            KotakTruncatedFrameError: The frame ends before a declared field.
        """
        topic_id = reader.read_signed_integer()
        topic_name = reader.read_text(reader.read_unsigned(1))
        numbers = []
        for _ in range(reader.read_unsigned(1)):
            numbers.append(reader.read_signed_integer())
        strings = {}
        for _ in range(reader.read_unsigned(1)):
            field_id = reader.read_unsigned(1)
            strings[field_id] = reader.read_text(reader.read_unsigned(1))

        kind, _, instrument_token = topic_name.partition("|")
        if kind not in (SCRIP_TOPIC, DEPTH_TOPIC):
            self._logger.warning(f"{self.name} ignored a snapshot for unexpected topic {topic_name!r}.")
            return None
        topic = KotakFeedTopic(kind, instrument_token, strings)
        topic.apply(numbers)
        self._topics[topic_id] = topic

        quote = self._quotes.get(instrument_token)
        if quote is None:
            quote = KotakInstrumentQuote(instrument_token)
            self._quotes[instrument_token] = quote
        if kind == SCRIP_TOPIC:
            quote.scrip = topic
        else:
            quote.depth = topic
        trading_symbol = strings.get(STRING_TRADING_SYMBOL)
        if trading_symbol and not self._names.get(instrument_token):
            self._names[instrument_token] = trading_symbol
            self._on_name(instrument_token, trading_symbol)
        return topic

    def _read_update(self, reader):
        """
        Reads an update packet and applies it to its topic.

        Args:
            reader (KotakFrameReader): The frame, positioned after the packet type.

        Returns:
            KotakFeedTopic | None: The topic, or None when no snapshot has registered its id on this connection.

        Raises:
            KotakTruncatedFrameError: The frame ends before a declared field.
        """
        topic_id = reader.read_signed_integer()
        numbers = []
        for _ in range(reader.read_unsigned(1)):
            numbers.append(reader.read_signed_integer())
        topic = self._topics.get(topic_id)
        if topic is None:
            self._logger.debug(f"{self.name} ignored an update for unknown topic id {topic_id}.")
            return None
        topic.apply(numbers)
        return topic

    def _hand_on_ticks(self, instrument_tokens):
        """
        Hands on the latest tick of each changed instrument that has had its scrip snapshot.

        Args:
            instrument_tokens (list[str]): The instruments whose topics changed, in arrival order.

        Returns:
            None: This method returns nothing.
        """
        ticks = []
        for instrument_token in instrument_tokens:
            tick = self._quotes[instrument_token].tick(self._names.get(instrument_token))
            if tick is not None:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)


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
