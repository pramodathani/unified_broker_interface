"""
Stoxkart's two websockets: the broadcast quote feed Stoxkart's website streams from, and the order update socket.

Neither is documented for API users, so Stoxkart may change them without notice.
Both read a synchronous websocket-client connection in a loop of their own, with their own silence and eviction handling, so neither subclasses `BrokerWebsocket`: `StoxkartQuoteStream` and `StoxkartOrderSocket` are the one exception to the package's shared reconnect loop.

**Quotes.**
Stoxkart's API documentation gives a binary quote websocket at `ws://inmob.stoxkart.com:7763`, which could not be reached on 2026-09-15; the website streams from `wss://broadcasting-v2.stoxkart.com/` instead, and the stream connects there.
The feed takes no login: the connection header's token field is left blank, exactly as the website sends it.
The protocol is Stoxkart's binary broadcast format, all little-endian.
A request is an 83-byte header - a request code (1 byte), the message length (2 bytes), a 30-byte client name and a blank 50-byte token - followed for a subscription by the exchange segment (1 byte), -1 (4 bytes), a scrip count of 1 (1 byte), a blank 20-byte watchlist name and the token as 20 bytes, 129 bytes in all.
The stream sends the connection header (code 10), then for each instrument a trade subscription (code 12) and a depth subscription (code 23).
Every answer is a run of packets, each starting with an 11-byte header: segment (1 byte), scrip id (4), a second id (4), packet length (1) and packet code (1).

| Code | Packet | Fields used |
| --- | --- | --- |
| 1 | Trade | last price, last quantity, volume, average price, open interest, last trade time, last update time |
| 2 | Depth | five levels of bid quantity, ask quantity, bid orders, ask orders, bid price, ask price |
| 3 | OHLC | open, high, low (its close is not used) |
| 6 | Top of book | total quantity offered, total quantity bid |
| 32 | Previous close | the previous session's close |

Circuit limits (33), the 52-week range (36) and any other packet are skipped.
The text `ping` is sent every five seconds and answered with `pong`; a socket silent for 30 seconds, or one that sends the text `reconnect`, is closed and opened again.
Stoxkart sends each instrument's packets together in one frame, so one tick is handed on per instrument per frame, and only when it differs from the previous tick apart from `received_at`.
Prices arrive as 32-bit floats in rupees and are rounded to four decimal places, which removes the float noise without touching a real tick.
Stoxkart counts seconds from 1980-01-01, the trade time in UTC and the update time on India's wall clock, so 315532800 seconds are added and, for the update time, 19800 taken off.

**Order updates.**
`StoxkartOrderSocket` first asks `POST https://openapi-v2.stoxkart.com/websocket/authenticate` for a RequestId, with the client code, the API access token, `x-platform: api` and the api key as headers, then opens `wss://openapi-v2.stoxkart.com/websocket/v2/connect?x-client-id=<client>&x-platform=api&RequestId=<RequestId>`.
It sends `{"type": "heartbeat"}` on connecting and every 30 seconds, as the website does, and updates arrive as JSON text.
Stoxkart keeps one order socket per client, and a new connection closes the older one with a close reason containing `new incoming connection`; the socket then waits five minutes before reclaiming it, so it and a logged-in website or app knock each other off at most that often.
An authentication refused with `AuthorizationError` logs in again before retrying.

Neither stream writes Redis.
The quote stream hands each frame's ticks to `on_ticks`, and the order socket hands each frame's messages to `on_updates`; the scripts in `bin/stoxkart/` do the writing.
"""

import json
import struct
import threading
import time
from datetime import datetime

FEED_URL = "wss://broadcasting-v2.stoxkart.com/"
CLIENT_NAME = b"unified_broker_interface"
CONNECTION_REQUEST_CODE = 10
TRADE_SUBSCRIBE_CODE = 12
DEPTH_SUBSCRIBE_CODE = 23
HEADER_LENGTH = 83
SUBSCRIBE_LENGTH = 129
PACKET_HEADER_LENGTH = 11
TRADE_PACKET = 1
DEPTH_PACKET = 2
OHLC_PACKET = 3
TOP_OF_BOOK_PACKET = 6
PREVIOUS_CLOSE_PACKET = 32
DEPTH_LEVELS = 5
EPOCH_1980_OFFSET_SECONDS = 315532800
INDIA_OFFSET_SECONDS = 19800
PING_INTERVAL_SECONDS = 5
SILENCE_LIMIT_SECONDS = 30
RECEIVE_TIMEOUT_SECONDS = 1
MINIMUM_BACKOFF_SECONDS = 1
MAXIMUM_BACKOFF_SECONDS = 60
REPORT_INTERVAL_SECONDS = 60
PRICE_DECIMALS = 4
SEGMENTS = {
    "NSE": 1,
    "NFO": 2,
    "BSE": 4,
    "MCX": 5,
}

AUTHENTICATE_URL = "https://openapi-v2.stoxkart.com/websocket/authenticate"
ORDER_SOCKET_URL = "wss://openapi-v2.stoxkart.com/websocket/v2/connect"
HEARTBEAT_SECONDS = 30
TIMEOUT_SECONDS = 15
EVICTED_WAIT_SECONDS = 300
EVICTION_REASON = "new incoming connection"


class StoxkartBroadcastRequests:
    """
    Builds the binary requests Stoxkart's broadcast websocket accepts.
    """

    def connection_header(self):
        """
        Builds the request that opens a session on the socket.

        Returns:
            bytes: The 83-byte connection header.
        """
        return self._header(CONNECTION_REQUEST_CODE, HEADER_LENGTH)

    def subscription(self, code, segment, token):
        """
        Builds a request that subscribes one instrument.

        Args:
            code (int): The subscription code, 12 for trades or 23 for depth.
            segment (int): The broadcast segment of the instrument's exchange.
            token (str): The instrument's token.

        Returns:
            bytes: The 129-byte subscription request.
        """
        body = struct.pack("<Bib20s20s", segment, -1, 1, b"", token.encode())
        return self._header(code, SUBSCRIBE_LENGTH) + body

    def _header(self, code, length):
        """
        Builds the header every request starts with.

        Args:
            code (int): The request code.
            length (int): The whole request's length in bytes.

        Returns:
            bytes: The 83-byte header with a blank token.
        """
        return struct.pack("<BH30s50s", code, length, CLIENT_NAME, b"")


class StoxkartInstrumentState:
    """
    The latest values Stoxkart's packets have given for one instrument, from which its tick is built.

    Attributes:
        instrument (str): The instrument as subscribed, `EXCHANGE:TOKEN`.
        name (str): The instrument's name, or an empty string.
        exchange (str): Stoxkart's exchange.
        values (dict): The latest value of every field the packets have supplied.
        depth (dict): The latest `buy` and `sell` levels.
    """

    def __init__(self, instrument, name):
        """
        Starts with no values.

        Args:
            instrument (str): The instrument as subscribed, `EXCHANGE:TOKEN`.
            name (str): The instrument's name, or an empty string.

        Returns:
            None: This method returns nothing.
        """
        self.instrument = instrument
        self.name = name
        self.exchange = instrument.split(":")[0]
        self.values = {}
        self.depth = {
            "buy": [],
            "sell": [],
        }
        self._previous_fingerprint = None

    def tick(self, received_at):
        """
        Builds the tick from the latest values.

        Args:
            received_at (float): The epoch at which the frame was decoded.

        Returns:
            dict | None: The tick, or None when no trade packet has arrived yet or nothing changed since the last tick.
        """
        if "last_price" not in self.values:
            return None
        values = self.values
        previous_close = values.get("previous_close")
        change = None
        if previous_close:
            change = round((values["last_price"] - previous_close) / previous_close * 100, 6)
        tick = {
            "id": self.name or self.instrument,
            "broker": "stoxkart",
            "instrument_token": self.instrument,
            "exchange": self.exchange,
            "mode": "full",
            "last_price": values.get("last_price"),
            "last_quantity": values.get("last_quantity"),
            "average_price": values.get("average_price"),
            "volume": values.get("volume"),
            "buy_quantity": values.get("buy_quantity"),
            "sell_quantity": values.get("sell_quantity"),
            "ohlc": {
                "open": values.get("open"),
                "high": values.get("high"),
                "low": values.get("low"),
                "close": previous_close,
            },
            "change": change,
            "oi": values.get("oi"),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": values.get("last_trade_time"),
            "exchange_timestamp": values.get("exchange_timestamp"),
            "depth": {
                "buy": list(self.depth["buy"]),
                "sell": list(self.depth["sell"]),
            },
        }
        fingerprint = json.dumps(tick, sort_keys=True)
        if fingerprint == self._previous_fingerprint:
            return None
        self._previous_fingerprint = fingerprint
        tick["received_at"] = received_at
        return tick


class StoxkartPacketDecoder:
    """
    Reads the packets in one broadcast frame into the instruments' states.
    """

    def __init__(self, states):
        """
        Remembers where each instrument's state is kept.

        Args:
            states (dict): Each `(segment, token)` pair mapped to its StoxkartInstrumentState.

        Returns:
            None: This method returns nothing.
        """
        self._states = states

    def decode(self, frame):
        """
        Applies every packet in a frame to its instrument's state.

        Args:
            frame (bytes): One binary websocket frame.

        Returns:
            list: The states the frame changed, each once.
        """
        touched = []
        offset = 0
        while offset + PACKET_HEADER_LENGTH <= len(frame):
            segment, scrip, _, length, code = struct.unpack_from("<BIIBB", frame, offset)
            if length < PACKET_HEADER_LENGTH:
                break
            body = frame[offset + PACKET_HEADER_LENGTH:offset + length]
            state = self._states.get((segment, scrip))
            if state is not None and self._apply(state, code, body) and state not in touched:
                touched.append(state)
            offset = offset + length
        return touched

    def _apply(self, state, code, body):
        """
        Applies one packet to an instrument's state.

        Args:
            state (StoxkartInstrumentState): The instrument's state.
            code (int): The packet code.
            body (bytes): The packet after its header.

        Returns:
            bool: True when the packet was one the stream reads and was long enough to read.
        """
        if code == TRADE_PACKET and len(body) >= 26:
            last_price, last_quantity, volume, average_price, open_interest, last_trade, last_update = struct.unpack_from("<fHIfiii", body)
            state.values["last_price"] = self._price(last_price)
            state.values["last_quantity"] = last_quantity
            state.values["volume"] = volume
            state.values["average_price"] = self._price(average_price)
            state.values["oi"] = open_interest
            state.values["last_trade_time"] = self._instant(last_trade, 0)
            state.values["exchange_timestamp"] = self._instant(last_update, INDIA_OFFSET_SECONDS)
            return True
        if code == DEPTH_PACKET and len(body) >= DEPTH_LEVELS * 20:
            buy_levels = []
            sell_levels = []
            for level in range(DEPTH_LEVELS):
                buy_quantity, sell_quantity, buy_orders, sell_orders, buy_price, sell_price = struct.unpack_from("<IIHHff", body, level * 20)
                buy_levels.append({
                    "quantity": buy_quantity,
                    "price": self._price(buy_price),
                    "orders": buy_orders,
                })
                sell_levels.append({
                    "quantity": sell_quantity,
                    "price": self._price(sell_price),
                    "orders": sell_orders,
                })
            state.depth["buy"] = buy_levels
            state.depth["sell"] = sell_levels
            return True
        if code == OHLC_PACKET and len(body) >= 16:
            day_open, _, day_high, day_low = struct.unpack_from("<ffff", body)
            state.values["open"] = self._price(day_open)
            state.values["high"] = self._price(day_high)
            state.values["low"] = self._price(day_low)
            return True
        if code == TOP_OF_BOOK_PACKET and len(body) >= 8:
            total_offered, total_bid = struct.unpack_from("<II", body)
            state.values["buy_quantity"] = total_bid
            state.values["sell_quantity"] = total_offered
            return True
        if code == PREVIOUS_CLOSE_PACKET and len(body) >= 4:
            state.values["previous_close"] = self._price(struct.unpack_from("<f", body)[0])
            return True
        return False

    def _price(self, value):
        """
        Rounds a 32-bit float price, treating zero as missing.

        Args:
            value (float): The price as decoded.

        Returns:
            float | None: The price rounded to four decimal places, or None when it is zero.
        """
        if not value:
            return None
        return round(value, PRICE_DECIMALS)

    def _instant(self, seconds, offset):
        """
        Converts Stoxkart's seconds since 1980 into epoch seconds.

        Args:
            seconds (int): The time as decoded.
            offset (int): Seconds to subtract, 19800 for a time counted on India's wall clock and 0 for UTC.

        Returns:
            int | None: Epoch seconds, or None when the time is zero or negative.
        """
        if seconds <= 0:
            return None
        return seconds + EPOCH_1980_OFFSET_SECONDS - offset


class StoxkartQuoteStream:
    """
    One connection to Stoxkart's broadcast websocket, reconnected until stopped.

    Attributes:
        logger (logging.Logger): Where connections, progress and failures are reported.
        stop (threading.Event): Set when streaming should end.
    """

    def __init__(self, instruments, names, on_ticks, logger):
        """
        Builds a state per instrument and the request builder.

        Args:
            instruments (list): The `EXCHANGE:TOKEN` strings to subscribe.
            names (dict): Each instrument mapped to its name, or to an empty string.
            on_ticks (callable): Called with each frame's list of changed ticks.
            logger (logging.Logger): Where connections, progress and failures are reported.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.stop = threading.Event()
        self._on_ticks = on_ticks
        self._requests = StoxkartBroadcastRequests()
        self._subscriptions = []
        states = {}
        for instrument in instruments:
            exchange, token = instrument.split(":")
            segment = SEGMENTS[exchange]
            states[(segment, int(token))] = StoxkartInstrumentState(instrument, names.get(instrument, ""))
            self._subscriptions.append((segment, token))
        self._decoder = StoxkartPacketDecoder(states)
        self._written_since_report = 0
        self._last_report_at = time.monotonic()

    def run(self):
        """
        Connects, subscribes and hands on ticks, reconnecting with a backoff, until stopped.

        Returns:
            int: 0, once stopped.
        """
        backoff = MINIMUM_BACKOFF_SECONDS
        while not self.stop.is_set():
            try:
                connected_for = self._stream_once()
            except Exception as error:
                self.logger.error(f"Broadcast socket failed, reconnecting in {backoff} seconds: {type(error).__name__}: {error}")
                connected_for = 0
            if self.stop.is_set():
                break
            if connected_for > MAXIMUM_BACKOFF_SECONDS:
                backoff = MINIMUM_BACKOFF_SECONDS
            self.stop.wait(backoff)
            backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)
        self.logger.info("Stopped")
        return 0

    def _stream_once(self):
        """
        Opens one connection and reads it until it fails, goes silent or is stopped.

        Returns:
            float: How many seconds the connection stayed up.

        Raises:
            websocket.WebSocketException: The connection could not be opened or broke.
        """
        import websocket

        socket = websocket.create_connection(FEED_URL, timeout=RECEIVE_TIMEOUT_SECONDS)
        opened_at = time.monotonic()
        try:
            socket.send_binary(self._requests.connection_header())
            for segment, token in self._subscriptions:
                socket.send_binary(self._requests.subscription(TRADE_SUBSCRIBE_CODE, segment, token))
                socket.send_binary(self._requests.subscription(DEPTH_SUBSCRIBE_CODE, segment, token))
            self.logger.info(f"Connected to {FEED_URL} and subscribed {len(self._subscriptions)} instrument(s).")
            self._read_until_closed(socket)
        finally:
            socket.close()
        return time.monotonic() - opened_at

    def _read_until_closed(self, socket):
        """
        Reads frames, pings the server and hands on ticks until the socket should be reopened or streaming stops.

        Args:
            socket (websocket.WebSocket): The open connection.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        last_message_at = time.monotonic()
        last_ping_at = time.monotonic()
        while not self.stop.is_set():
            now = time.monotonic()
            if now - last_ping_at >= PING_INTERVAL_SECONDS:
                socket.send("ping")
                last_ping_at = now
            if now - last_message_at > SILENCE_LIMIT_SECONDS:
                self.logger.warning(f"No message for {SILENCE_LIMIT_SECONDS} seconds, reconnecting.")
                return
            try:
                opcode, frame = socket.recv_data()
            except websocket.WebSocketTimeoutException:
                continue
            last_message_at = time.monotonic()
            if opcode == websocket.ABNF.OPCODE_TEXT:
                if frame == b"reconnect":
                    self.logger.warning("Stoxkart asked for a reconnect.")
                    return
                continue
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                self.logger.warning("Stoxkart closed the broadcast socket.")
                return
            if opcode == websocket.ABNF.OPCODE_BINARY:
                self._hand_on(self._decoder.decode(frame))

    def _hand_on(self, states):
        """
        Hands on a tick for every instrument a frame changed.

        Args:
            states (list): The instrument states the frame changed.

        Returns:
            None: This method returns nothing.
        """
        received_at = time.time()
        ticks = []
        for state in states:
            tick = state.tick(received_at)
            if tick is not None:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)
        self._report(len(ticks))

    def _report(self, written):
        """
        Adds a frame's count to the running total and logs the total once a minute.

        Args:
            written (int): How many ticks the frame handed on.

        Returns:
            None: This method returns nothing.
        """
        self._written_since_report = self._written_since_report + written
        if time.monotonic() - self._last_report_at < REPORT_INTERVAL_SECONDS:
            return
        self.logger.info(f"Wrote {self._written_since_report} tick(s) in the last minute to stoxkart:quotes:live")
        self._written_since_report = 0
        self._last_report_at = time.monotonic()


class StoxkartSessionRefused(Exception):
    """Stoxkart refused the order socket's authentication because the session is dead."""


class StoxkartSession:
    """
    The Stoxkart API login the order socket authenticates with.
    """

    def __init__(self):
        """
        Constructs `StoxkartAPI`, which logs in when the stored session is dead.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `StoxkartAPI` raises when it cannot log in.
        """
        from stock_brokers.api.stoxkart import StoxkartAPI

        self._api_class = StoxkartAPI
        self._stoxkart = StoxkartAPI()

    def authentication_headers(self):
        """
        The headers the order socket's authentication request carries, with the access token in force now.

        Returns:
            dict: The headers.
        """
        login = self._stoxkart._current_login() or {}
        settings = self._stoxkart._settings
        return {
            "x-client-id": settings["ucc_code"],
            "x-access-token": login.get("access_token") or "",
            "x-platform": "api",
            "x-api-key": settings["api_key"],
        }

    def client_id(self):
        """
        The client code the order socket connects as.

        Returns:
            str: The `ucc_code` setting.
        """
        return self._stoxkart._settings["ucc_code"]

    def log_in_again(self):
        """
        Logs in again by constructing `StoxkartAPI` again.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `StoxkartAPI` raises when it cannot log in.
        """
        self._stoxkart = self._api_class()


class StoxkartOrderSocket:
    """
    The order update websocket, authenticated with the API session and reconnected until stopped.

    Attributes:
        logger (logging.Logger): Where connections, updates and failures are reported.
        stop (threading.Event): Set when streaming should end.
    """

    def __init__(self, session, on_updates, logger):
        """
        Remembers the session and where updates go.

        Args:
            session (StoxkartSession): The logged-in API session whose token authenticates the socket.
            on_updates (callable): Called with each frame's messages, as dictionaries exactly as Stoxkart sent them, and the `datetime` the frame was read.
            logger (logging.Logger): Where connections, updates and failures are reported.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger
        self.stop = threading.Event()
        self._session = session
        self._on_updates = on_updates

    def run(self):
        """
        Authenticates, connects and hands on updates, reconnecting with a backoff, until stopped.

        Returns:
            int: 0 once stopped, and 1 when logging in again after a refused session failed.
        """
        backoff = MINIMUM_BACKOFF_SECONDS
        while not self.stop.is_set():
            wait = backoff
            try:
                request_id = self._authenticate()
                close_reason = self._stream(request_id)
                backoff = MINIMUM_BACKOFF_SECONDS
                wait = MINIMUM_BACKOFF_SECONDS
                if EVICTION_REASON in close_reason.lower():
                    self.logger.warning(f"Another Stoxkart session took the order socket; reclaiming it in {EVICTED_WAIT_SECONDS} seconds.")
                    wait = EVICTED_WAIT_SECONDS
            except StoxkartSessionRefused as error:
                self.logger.warning(f"Stoxkart session expired, logging in again: {error}")
                try:
                    self._session.log_in_again()
                except Exception as login_error:
                    self.logger.error(f"Could not log in to Stoxkart: {type(login_error).__name__}: {login_error}")
                    return 1
                wait = 0
            except Exception as error:
                self.logger.error(f"Order socket failed, reconnecting in {backoff} seconds: {type(error).__name__}: {error}")
                backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)
            if wait:
                self.stop.wait(wait)
        self.logger.info("Stopped")
        return 0

    def _authenticate(self):
        """
        Asks Stoxkart for the RequestId the socket connects with.

        Returns:
            str: The RequestId.

        Raises:
            StoxkartSessionRefused: Stoxkart refused the access token.
            RuntimeError: Stoxkart answered without a RequestId.
            requests.RequestException: The request could not be sent.
        """
        import requests

        response = requests.post(AUTHENTICATE_URL, headers=self._session.authentication_headers(), timeout=TIMEOUT_SECONDS)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 401 or body.get("code") == "AuthorizationError":
            raise StoxkartSessionRefused(body.get("message") or f"HTTP {response.status_code}")
        request_id = (body.get("data") or {}).get("RequestId")
        if response.status_code >= 300 or not request_id:
            raise RuntimeError(f"authentication answered HTTP {response.status_code}: {response.text[:200]}")
        return request_id

    def _stream(self, request_id):
        """
        Opens the socket and reads it until it closes or streaming stops.

        Args:
            request_id (str): The RequestId from the authentication.

        Returns:
            str: The close reason Stoxkart gave, or an empty string.

        Raises:
            websocket.WebSocketException: The socket could not be opened or broke.
        """
        import websocket

        url = f"{ORDER_SOCKET_URL}?x-client-id={self._session.client_id()}&x-platform=api&RequestId={request_id}"
        socket = websocket.create_connection(url, timeout=RECEIVE_TIMEOUT_SECONDS)
        self.logger.info(f"Connected to {ORDER_SOCKET_URL}.")
        try:
            return self._read(socket)
        finally:
            socket.close()

    def _read(self, socket):
        """
        Sends heartbeats and hands on updates until the socket closes or streaming stops.

        Args:
            socket (websocket.WebSocket): The open connection.

        Returns:
            str: The close reason Stoxkart gave, or an empty string.
        """
        import websocket

        heartbeat = json.dumps({"type": "heartbeat"})
        socket.send(heartbeat)
        last_heartbeat_at = time.monotonic()
        while not self.stop.is_set():
            if time.monotonic() - last_heartbeat_at >= HEARTBEAT_SECONDS:
                socket.send(heartbeat)
                last_heartbeat_at = time.monotonic()
            try:
                opcode, frame = socket.recv_data()
            except websocket.WebSocketTimeoutException:
                continue
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                reason = frame[2:].decode("utf-8", errors="replace")
                self.logger.warning(f"Stoxkart closed the order socket: {reason!r}")
                return reason
            if opcode == websocket.ABNF.OPCODE_TEXT:
                self._handle(frame.decode("utf-8", errors="replace"))
        return ""

    def _handle(self, text):
        """
        Logs every message in one text frame and hands them on.

        Args:
            text (str): The frame's text.

        Returns:
            None: This method returns nothing.
        """
        try:
            payload = json.loads(text)
        except ValueError:
            self.logger.info(f"Ignoring a frame that is not JSON: {text[:200]}")
            return
        items = payload
        if not isinstance(payload, list):
            items = [payload]

        received_at = datetime.now()
        messages = []
        for item in items:
            if not isinstance(item, dict):
                continue
            self.logger.info(f"Order socket message: {json.dumps(item)[:300]}")
            messages.append(item)
        if messages:
            self._on_updates(messages, received_at)
