"""
Wisdom Capital's two XTS websockets: the market data feed and the interactive (trading) namespace that pushes order and position events.

**Two applications, two sessions.**
XTS splits a broker into a market data application and an interactive one.
Quotes need the market data session, whose token is minted from `price_api_key` and `price_api_secret`; XTS issues exactly one per application key, and a second login invalidates the first.
`WisdomCapitalMarketDataSession` reads the market data token from the shared login and asks `WisdomCapitalAPI` to replace it when it is refused, which the API does under a Redis lock, and only when nobody has replaced it already.
Orders and positions live in the interactive application, which also keeps one session per key: `WisdomCapitalInteractiveSession` joins with the token `WisdomCapitalAPI` shares through `last_login`, reads the user id from that token's JWT payload, and never logs in for itself except by constructing `WisdomCapitalAPI` again, which keeps a stored token that still works.

**The transport.**
The host's certificate is issued to the platform provider's domain, so the exact certificate is pinned instead of the hostname being checked: HTTPS requests go through a urllib3 pool that asserts the fingerprint, and a websocket's certificate is compared with the pin as soon as it opens.
A connection opens an Engine.IO session over HTTPS polling, attaches a websocket with the session id, sends the `2probe` probe, answers `3probe` with `5` to complete the upgrade, and then pings (`2`) at half the shorter of the ping interval and timeout the server asked for, since the two disagree and the interactive namespace waits only twenty seconds.
A server ping is answered with `3`.
XTS reports a refused token with `e-session`, `e-token` or "Invalid Token" in the answer.

**Quotes.**
`WisdomCapitalQuotesSocket` attaches with `publishFormat=JSON&broadcastMode=Full` and subscribes over REST, for touchline (1501) and market depth (1502); the answer carries the current snapshot, which is handed on straight away.
XTS reports instruments still subscribed from an earlier connection as `e-session-0002 Instrument Already Subscribed`, with the same prefix as a refused token, so that answer is met by dropping the subscription and asking again rather than by replacing a good token.
Events arrive as socket.io frames `42["<event>", <payload>]`, the payload a quote, a list of them, or either as a JSON string; touchline and depth for one instrument are merged, a depth message nesting its touchline fields, before a tick is built.
XTS counts seconds from 1980-01-01 in India time, so its timestamps are moved onto the true Unix epoch, and it misspells the last traded quantity as `LastTradedQunatity`, sending the key with a null value.
A tick with neither a price nor a book is not handed on.

**Order updates.**
`WisdomCapitalOrderUpdatesSocket` joins the interactive namespace with `apiType=INTERACTIVE`, which is enough for XTS to push every order, trade and position event for the account; without it the server cuts the connection after ten seconds.
When another login replaces the token, XTS sends a `logout` event and leaves the connection open while delivering nothing more, so the socket closes, waits up to ten seconds for the replacing login to reach Redis, and reconnects with it; this wait is why the socket keeps a reconnect loop of its own.
A `trade` event is not handed on, because the order event that follows carries the fill.

Neither socket writes Redis.
The quotes socket hands ticks to `on_ticks`, and the order socket hands each event's orders or positions to `on_updates`; the scripts in `bin/wisdom_capital/` do the writing.
"""

import base64
import hashlib
import json
import ssl
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

HOST = "trade.wisdomcapital.in"
PORT = 443
MARKET_DATA_PATH = "/apimarketdata"
INTERACTIVE_PATH = "/interactive"

CERTIFICATE_FINGERPRINT = "1ACF7CA747F2D678B6CB7E01189FE43142DE8B2A2039231F905F9C5E6AB1F7AF"

SEGMENT_NAMES = {
    1: "NSECM",
    2: "NSEFO",
    3: "NSECD",
    4: "NSECO",
    11: "BSECM",
    12: "BSEFO",
    13: "BSECD",
    21: "NCDEX",
    51: "MCXFO",
}

TOUCHLINE = 1501
MARKET_DEPTH = 1502

EPOCH_OFFSET_SECONDS = 315513000

AUTHENTICATION_MARKERS = (
    "e-session",
    "e-token",
    "invalid token",
)
ALREADY_SUBSCRIBED_MARKER = "already subscribed"

QUOTES_HEARTBEAT_SECONDS = 25.0
ORDER_UPDATES_HEARTBEAT_SECONDS = 10.0
REPLACEMENT_LOGIN_WAIT_SECONDS = 10


class WisdomCapitalTransport:
    """
    The pinned HTTPS requests, the Engine.IO handshake and the heartbeat both XTS sockets use.
    """

    def request(self, method, path, token=None, body=None):
        """
        Sends an HTTPS request to the platform over a connection pinned to its certificate.

        Args:
            method (str): The HTTP method.
            path (str): The path to request.
            token (str | None): The token to send as `authorization`, if any.
            body (object | None): An object to send as JSON, if any.

        Returns:
            urllib3.response.HTTPResponse: The response.

        Raises:
            urllib3.exceptions.HTTPError: When the request fails or the certificate does not match the pin.
        """
        import urllib3

        headers = {
            "Content-Type": "application/json",
        }
        if token:
            headers["authorization"] = token
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(body)
        pool = urllib3.HTTPSConnectionPool(HOST, PORT, assert_fingerprint=CERTIFICATE_FINGERPRINT)
        return pool.request(method, path, body=encoded_body, headers=headers, timeout=30)

    def handshake(self, path, query):
        """
        Opens an Engine.IO session over HTTPS polling.

        Args:
            path (str): The application path, market data or interactive.
            query (str): The query string that authenticates the session.

        Returns:
            tuple: The decoded handshake, or None when it was refused or unreadable, and the answer's status and body for reporting.
        """
        response = self.request("GET", f"{path}/socket.io/?EIO=3&transport=polling&{query}")
        body = response.data.decode("utf-8", errors="replace")
        handshake = None
        if response.status < 300:
            handshake = self.first_json_object(body)
        if not handshake or not handshake.get("sid"):
            handshake = None
        return handshake, response.status, body

    def first_json_object(self, text):
        """
        The first balanced `{...}` in an Engine.IO polling body, which frames the handshake JSON with a length prefix.

        Args:
            text (str): The body.

        Returns:
            dict | None: The decoded object, or None when there is none.
        """
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth = depth + 1
            elif text[index] == "}":
                depth = depth - 1
            if depth == 0:
                return json.loads(text[start:index + 1])
        return None

    def heartbeat_seconds(self, handshake, default_seconds):
        """
        Half the shorter of the ping interval and timeout the server asked for, so a ping sits inside both.

        Args:
            handshake (dict): The decoded Engine.IO handshake.
            default_seconds (float): The interval to use when the server asked for neither.

        Returns:
            float: The interval in seconds, at least one.
        """
        limits = []
        for value in (handshake.get("pingInterval"), handshake.get("pingTimeout")):
            if value:
                limits.append(float(value) / 1000.0)
        if not limits:
            return default_seconds
        return max(1.0, min(limits) / 2.0)

    def websocket_url(self, path, handshake, query):
        """
        The websocket URL that attaches to an Engine.IO session.

        Args:
            path (str): The application path, market data or interactive.
            handshake (dict): The decoded Engine.IO handshake.
            query (str): The query string that authenticates the session.

        Returns:
            str: The URL.
        """
        return f"wss://{HOST}{path}/socket.io/?EIO=3&transport=websocket&sid={handshake['sid']}&{query}"

    def ssl_options(self):
        """
        The TLS options for the websocket: the chain verified and the hostname check relaxed, since the pin is checked once it opens.

        Returns:
            dict: The `sslopt` websocket-client takes.
        """
        context = ssl.create_default_context()
        context.check_hostname = False
        return {
            "context": context,
        }

    def peer_fingerprint(self, websocket_connection):
        """
        The SHA-256 fingerprint of the certificate an open websocket's peer presented.

        Args:
            websocket_connection (websocket.WebSocketApp): The open connection.

        Returns:
            str: The fingerprint in upper case hex, or the pinned one when the certificate cannot be read.
        """
        try:
            return hashlib.sha256(websocket_connection.sock.sock.getpeercert(True)).hexdigest().upper()
        except (AttributeError, TypeError):
            return CERTIFICATE_FINGERPRINT

    def start_heartbeat(self, websocket_connection, closed, interval, stop, thread_name):
        """
        Starts a thread that sends the Engine.IO ping on the interval the server asked for, until the connection closes.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection to ping.
            closed (threading.Event): Set when this connection closes.
            interval (float): The interval in seconds.
            stop (threading.Event): Set when the socket is stopped.
            thread_name (str): The thread's name.

        Returns:
            None: This method returns nothing.
        """
        thread = threading.Thread(
            target=self._send_heartbeats,
            args=(websocket_connection, closed, interval, stop),
            name=thread_name,
            daemon=True,
        )
        thread.start()

    def _send_heartbeats(self, websocket_connection, closed, interval, stop):
        """
        Sends `2` every interval until the connection closes, the socket stops, or a send fails.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection to ping.
            closed (threading.Event): Set when this connection closes.
            interval (float): The interval in seconds.
            stop (threading.Event): Set when the socket is stopped.

        Returns:
            None: This method returns nothing.
        """
        while not closed.wait(interval) and not stop.is_set():
            try:
                websocket_connection.send("2")
            except Exception:
                return

    def is_authentication_refusal(self, text):
        """
        Whether an answer says the token was refused.

        Args:
            text (str): The answer's body.

        Returns:
            bool: True for a refused token.
        """
        lowered = str(text).lower()
        for marker in AUTHENTICATION_MARKERS:
            if marker in lowered:
                return True
        return False


class WisdomCapitalMarketDataSession:
    """
    The market data login every quotes socket authenticates with.
    """

    def __init__(self, logger):
        """
        Constructs `WisdomCapitalAPI`, which establishes both of Wisdom Capital's sessions when either has stopped working.

        Args:
            logger (logging.Logger): Where token replacements are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `WisdomCapitalAPI` raises, or the market data login failure it recorded.
        """
        from stock_brokers.api.wisdom_capital import WisdomCapitalAPI

        self._api = WisdomCapitalAPI()
        self._logger = logger
        self._lock = threading.Lock()
        if self._api.market_data_session_error:
            raise self._api.market_data_session_error

    def market_data(self):
        """
        The market data session in force now.

        Returns:
            dict: `access_token` and `user_id`.
        """
        return self._api.market_data_session()

    def replace(self, stale_token):
        """
        Replaces a refused market data token, unless another socket or process already has.

        Args:
            stale_token (str | None): The token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `WisdomCapitalAPI` raises when it cannot log in.
        """
        with self._lock:
            self._logger.warning("Replacing the Wisdom Capital market data token.")
            self._api.replace_market_data_session(stale_access_token=stale_token)


class WisdomCapitalInteractiveSession:
    """
    The interactive login the order updates socket joins with, shared with every Wisdom Capital process.
    """

    def __init__(self, logger):
        """
        Constructs `WisdomCapitalAPI`, which logs in when the stored session is dead.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `WisdomCapitalAPI` raises when it cannot log in.
        """
        from stock_brokers.api.wisdom_capital import WisdomCapitalAPI

        self._api_class = WisdomCapitalAPI
        self._api = WisdomCapitalAPI()
        self._logger = logger

    def current_token(self):
        """
        The interactive token stored in the shared login now.

        Returns:
            str | None: The token, or None when none is stored.
        """
        login = self._api._current_login() or {}
        return login.get("access_token")

    def shared_login(self):
        """
        The interactive token every Wisdom Capital process shares, and the user id it was issued to.

        Returns:
            tuple: The access token and the user id.

        Raises:
            RuntimeError: No usable token is stored, or the stored token carries no user id.
        """
        token = self.current_token()
        if not token or token == "None":
            raise RuntimeError("no Wisdom Capital access token is stored in last_login")
        user_id = self._user_id_from_token(token)
        if user_id is None:
            raise RuntimeError("the stored Wisdom Capital access token carries no userID")
        return token, user_id

    def log_in_again_without_checking(self):
        """
        Constructs `WisdomCapitalAPI` again, which keeps a stored token that still works and logs in only when it does not.

        Returns:
            None: This method returns nothing.

        Raises:
            Exception: Whatever `WisdomCapitalAPI` raises when it cannot log in.
        """
        self._logger.warning("Checking the Wisdom Capital login, and logging in again if it is dead.")
        self._api = self._api_class()

    def _user_id_from_token(self, token):
        """
        The user id XTS signs into an interactive token.

        Args:
            token (str): The interactive access token, a JWT.

        Returns:
            str | None: The token's `userID` claim, or None when the token is not a readable JWT or has no such claim.
        """
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padded_payload = parts[1] + "=" * (-len(parts[1]) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode(padded_payload))
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload.get("userID")


class WisdomCapitalQuotesSocket(BrokerWebsocket):
    """
    One XTS market data socket carrying the touchline and depth of a batch of instruments.
    """

    def __init__(self, name, tokens, names, session, on_ticks, logger):
        """
        Sets up a socket for one batch of instruments.

        Args:
            name (str): The connection's name, for the log.
            tokens (list[str]): The batch of `SEGMENT:EXCHANGEINSTRUMENTID` instrument tokens.
            names (dict[str, str]): Each token to the instrument's name, which becomes a tick's `id`.
            session (WisdomCapitalMarketDataSession): The shared market data login.
            on_ticks (callable): Called with each list of ticks that carry a price or a book, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._tokens = tokens
        self._names = names
        self._session = session
        self._on_ticks = on_ticks
        self._transport = WisdomCapitalTransport()
        self._token = None
        self._heartbeat_seconds = QUOTES_HEARTBEAT_SECONDS
        self._connection_closed = threading.Event()
        self._state = {}

    def _connect(self):
        """
        Opens an Engine.IO session with the market data token in force now, attaches the websocket and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: When the Engine.IO handshake is refused.
        """
        import websocket

        session = self._session.market_data()
        self._token = session["access_token"]
        user_id = session["user_id"]
        query = f"token={self._token}&userID={user_id}&publishFormat=JSON&broadcastMode=Full"

        handshake, status, body = self._transport.handshake(MARKET_DATA_PATH, query)
        if handshake is None:
            self._authentication_rejected = self._transport.is_authentication_refusal(body)
            raise RuntimeError(f"Engine.IO handshake failed with {status}: {body[:200]}")
        self._heartbeat_seconds = self._transport.heartbeat_seconds(handshake, QUOTES_HEARTBEAT_SECONDS)

        self._connection_closed = threading.Event()
        self._websocket_application = websocket.WebSocketApp(
            self._transport.websocket_url(MARKET_DATA_PATH, handshake, query),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(sslopt=self._transport.ssl_options())

    def _log_in_again(self):
        """
        Replaces the refused market data token, unless another socket or process already has.

        Returns:
            None: This method returns nothing.
        """
        self._session.replace(self._token)

    def _on_open(self, websocket_connection):
        """
        Checks the pinned certificate, then begins the Engine.IO upgrade.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        fingerprint = self._transport.peer_fingerprint(websocket_connection)
        if fingerprint != CERTIFICATE_FINGERPRINT:
            self._logger.error(f"{self.name}: {HOST} presented certificate {fingerprint}, which does not match the pin. If Wisdom Capital has renewed, refresh CERTIFICATE_FINGERPRINT.")
            websocket_connection.close()
            return
        self._opened = True
        self._state = {}
        websocket_connection.send("2probe")

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

    def _on_close(self, websocket_connection, status_code, message):
        """
        Stops this connection's heartbeat and reports that the connection closed.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that closed.
            status_code (int | None): The close status.
            message (str | None): The close reason.

        Returns:
            None: This method returns nothing.
        """
        self._connection_closed.set()
        super()._on_close(websocket_connection, status_code, message)

    def _on_message(self, websocket_connection, message):
        """
        Handles Engine.IO control frames and hands on the quotes each socket.io event carries.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        if message == "3probe":
            websocket_connection.send("5")
            self._transport.start_heartbeat(
                websocket_connection,
                self._connection_closed,
                self._heartbeat_seconds,
                self._stop,
                f"wisdom_capital_quotes_{self.name}_heartbeat",
            )
            self._subscribe(websocket_connection)
            return
        if message == "2":
            websocket_connection.send("3")
            return
        ticks = []
        for token in self._apply_events(message):
            ticks.append(self._tick(token))
        self._hand_on(ticks)

    def _subscribe(self, websocket_connection):
        """
        Subscribes the batch over REST for touchline and depth, and hands on the snapshot the answer carries.

        Args:
            websocket_connection (websocket.WebSocketApp): The open connection, closed when the token is refused.

        Returns:
            None: This method returns nothing.
        """
        instruments = []
        for token in self._tokens:
            instruments.append({
                "exchangeSegment": int(token.split(":")[0]),
                "exchangeInstrumentID": int(token.split(":")[1]),
            })
        seeded = set()
        for code in (TOUCHLINE, MARKET_DEPTH):
            response, body = self._ask_to_subscribe(instruments, code)
            if response.status >= 300 and ALREADY_SUBSCRIBED_MARKER in str(body).lower():
                self._logger.info(f"{self.name}: message code {code} is still subscribed from an earlier connection. Dropping that subscription and asking again.")
                self._transport.request(
                    "PUT",
                    f"{MARKET_DATA_PATH}/instruments/subscription",
                    token=self._token,
                    body={"instruments": instruments, "xtsMessageCode": code},
                )
                response, body = self._ask_to_subscribe(instruments, code)
            if response.status >= 300:
                if self._transport.is_authentication_refusal(body):
                    self._logger.warning(f"{self.name}: subscription refused the market data token: {body[:200]}")
                    self._authentication_rejected = True
                    websocket_connection.close()
                    return
                self._logger.warning(f"{self.name}: subscription for message code {code} returned {response.status}: {body[:200]}")
                continue
            try:
                quotes = (json.loads(body).get("result") or {}).get("listQuotes") or []
            except (ValueError, AttributeError):
                quotes = []
            for quote in quotes:
                if isinstance(quote, str):
                    quote = json.loads(quote)
                token = self._apply_quote(quote)
                if token:
                    seeded.add(token)
        ticks = []
        for token in seeded:
            ticks.append(self._tick(token))
        self._hand_on(ticks)
        self._logger.info(f"{self.name} subscribed to {len(self._tokens)} instrument(s).")

    def _ask_to_subscribe(self, instruments, code):
        """
        Asks for one message code's subscription.

        Args:
            instruments (list[dict]): The batch as XTS wants it, segment and instrument id per entry.
            code (int): The XTS message code, touchline or market depth.

        Returns:
            tuple: The response and its decoded body.
        """
        response = self._transport.request(
            "POST",
            f"{MARKET_DATA_PATH}/instruments/subscription",
            token=self._token,
            body={"instruments": instruments, "xtsMessageCode": code},
        )
        return response, response.data.decode("utf-8", errors="replace")

    def _apply_events(self, message):
        """
        Merges the quotes in a frame's socket.io event into their instruments' state.

        Args:
            message (str): The frame; only `42[...]` event frames carry quotes.

        Returns:
            list[str]: The tokens whose state the event updated, each once, in order.
        """
        if not isinstance(message, str) or not message.startswith("42"):
            return []
        try:
            event = json.loads(message[2:])
        except json.JSONDecodeError:
            return []
        if not isinstance(event, list) or len(event) < 2:
            return []
        payload = event[1]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return []
        quotes = payload
        if not isinstance(payload, list):
            quotes = [payload]
        tokens = []
        for quote in quotes:
            token = self._apply_quote(quote)
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    def _apply_quote(self, quote):
        """
        Merges an XTS quote into its instrument's state, a depth message's nested touchline included.

        Args:
            quote (object): A decoded XTS quote.

        Returns:
            str | None: The instrument's token, or None for something that is not a quote.
        """
        if not isinstance(quote, dict) or quote.get("ExchangeSegment") is None or quote.get("ExchangeInstrumentID") is None:
            return None
        token = f"{quote['ExchangeSegment']}:{quote['ExchangeInstrumentID']}"
        state = self._state.setdefault(token, {})
        state.update(quote)
        touchline = quote.get("Touchline")
        if isinstance(touchline, dict):
            state.update(touchline)
        return token

    def _tick(self, token):
        """
        Builds a normalized tick from an instrument's merged state.

        Args:
            token (str): The instrument's `SEGMENT:EXCHANGEINSTRUMENTID`.

        Returns:
            dict: The tick.
        """
        state = self._state.get(token) or {}
        depth = {
            "buy": self._levels(state.get("Bids")),
            "sell": self._levels(state.get("Asks")),
        }
        if not depth["buy"] and isinstance(state.get("BidInfo"), dict):
            depth["buy"] = self._levels([state["BidInfo"]])
        if not depth["sell"] and isinstance(state.get("AskInfo"), dict):
            depth["sell"] = self._levels([state["AskInfo"]])
        last_price = state.get("LastTradedPrice")
        close = state.get("Close")
        segment = state.get("ExchangeSegment")
        exchange = SEGMENT_NAMES.get(segment)
        if exchange is None and segment is not None:
            exchange = str(segment)
        mode = "quote"
        if depth["buy"] or depth["sell"]:
            mode = "full"
        last_quantity = state.get("LastTradedQunatity")
        if last_quantity is None:
            last_quantity = state.get("LastTradedQuantity")
        change = None
        if last_price is not None and close:
            change = (last_price - close) * 100 / close
        return {
            "id": self._names.get(token) or token,
            "broker": "wisdom_capital",
            "instrument_token": token,
            "exchange": exchange,
            "mode": mode,
            "last_price": last_price,
            "last_quantity": last_quantity,
            "average_price": state.get("AverageTradedPrice"),
            "volume": state.get("TotalTradedQuantity"),
            "buy_quantity": state.get("TotalBuyQuantity"),
            "sell_quantity": state.get("TotalSellQuantity"),
            "ohlc": {
                "open": state.get("Open"),
                "high": state.get("High"),
                "low": state.get("Low"),
                "close": close,
            },
            "change": change,
            "oi": state.get("OpenInterest"),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": self._true_epoch(state.get("LastTradedTime")),
            "exchange_timestamp": self._true_epoch(state.get("ExchangeTimeStamp") or state.get("LastUpdateTime")),
            "depth": depth,
            "received_at": time.time(),
        }

    def _levels(self, rows):
        """
        Depth levels from an XTS bid or ask list, without the zero rows XTS pads the book with.

        Args:
            rows (list | None): The depth rows.

        Returns:
            list[dict]: The levels.
        """
        levels = []
        for row in rows or []:
            if isinstance(row, dict) and (row.get("Price") or row.get("Size")):
                levels.append({
                    "quantity": row.get("Size"),
                    "price": row.get("Price"),
                    "orders": row.get("TotalOrders"),
                })
        return levels

    def _true_epoch(self, timestamp):
        """
        An XTS timestamp on the true Unix epoch.

        Args:
            timestamp (int | None): The timestamp XTS sent.

        Returns:
            int | None: The epoch, or None for a missing one.
        """
        if timestamp:
            return timestamp + EPOCH_OFFSET_SECONDS
        return None

    def _hand_on(self, ticks):
        """
        Hands on the ticks that carry a price or a book.

        Args:
            ticks (list[dict]): The ticks.

        Returns:
            None: This method returns nothing.
        """
        worth_writing = []
        for tick in ticks:
            if tick["last_price"] is not None or tick["depth"]["buy"] or tick["depth"]["sell"]:
                worth_writing.append(tick)
        if worth_writing:
            self._on_ticks(worth_writing)


class WisdomCapitalOrderUpdatesSocket(BrokerWebsocket):
    """
    Wisdom Capital's XTS interactive socket, which carries the account's order and position events.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (WisdomCapitalInteractiveSession): The shared interactive login.
            on_updates (callable): Called on this socket's thread with an event's orders, its positions and the `datetime` it was received, one of the two lists empty, each entry exactly as XTS sent it.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates
        self._transport = WisdomCapitalTransport()
        self._logged_out = False
        self._token = None
        self._heartbeat_seconds = ORDER_UPDATES_HEARTBEAT_SECONDS
        self._connection_closed = threading.Event()

    def run_forever(self):
        """
        Connects, and reconnects with backoff, until closed or unable to recover, waiting after a logout for the login that replaced this one.

        This is `BrokerWebsocket.run_forever` with one step added: after XTS logs the socket out, it waits for the replacing login to reach Redis, and treats a token that is still the logged-out one as a refused session.

        Returns:
            None: This method returns nothing. `gave_up` says whether the socket stopped because it could not recover.
        """
        backoff = self.MIN_BACKOFF_SECONDS
        failed_connects = 0
        logged_in_again = False
        while not self._stop.is_set():
            self._opened = False
            self._authentication_rejected = False
            self._logged_out = False
            try:
                self._connect()
            except Exception as exception:
                self._logger.error(f"{self.name} connection failed: {type(exception).__name__}: {exception}")
            if self._stop.is_set():
                break

            if self._logged_out and not self._wait_for_replacement_login():
                if self._stop.is_set():
                    break
                self._logger.warning("The stored Wisdom Capital token is still the one that was logged out.")
                self._authentication_rejected = True

            if self._opened and not self._authentication_rejected:
                failed_connects = 0
                logged_in_again = False
                backoff = self.MIN_BACKOFF_SECONDS
            else:
                failed_connects = failed_connects + 1

            if self._authentication_rejected or failed_connects >= self.MAX_FAILED_CONNECTS:
                if logged_in_again:
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

    def _wait_for_replacement_login(self):
        """
        Waits for the login that logged this socket out to reach the shared `last_login` hash.

        Returns:
            bool: True when the shared login holds a token other than the one this connection used, and False when it still holds that token after `REPLACEMENT_LOGIN_WAIT_SECONDS` or the socket is stopped first.
        """
        deadline = time.monotonic() + REPLACEMENT_LOGIN_WAIT_SECONDS
        while not self._stop.is_set():
            if self._session.current_token() != self._token:
                return True
            if time.monotonic() >= deadline:
                return False
            self._stop.wait(1)
        return False

    def _connect(self):
        """
        Opens an Engine.IO session with the shared login, attaches the websocket and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            RuntimeError: No usable token is stored, or the Engine.IO handshake is refused.
        """
        import websocket

        try:
            token, user_id = self._session.shared_login()
        except RuntimeError:
            self._authentication_rejected = True
            raise
        self._token = token
        query = f"token={token}&userID={user_id}&apiType=INTERACTIVE"

        handshake, status, body = self._transport.handshake(INTERACTIVE_PATH, query)
        if handshake is None:
            self._authentication_rejected = self._transport.is_authentication_refusal(body)
            raise RuntimeError(f"Engine.IO handshake failed with {status}: {body[:200]}")
        self._heartbeat_seconds = self._transport.heartbeat_seconds(handshake, ORDER_UPDATES_HEARTBEAT_SECONDS)

        self._connection_closed = threading.Event()
        self._websocket_application = websocket.WebSocketApp(
            self._transport.websocket_url(INTERACTIVE_PATH, handshake, query),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._websocket_application.run_forever(sslopt=self._transport.ssl_options())

    def _log_in_again(self):
        """
        Constructs the API again, without checking whether another process already replaced the token.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Checks the pinned certificate, then begins the Engine.IO upgrade.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        fingerprint = self._transport.peer_fingerprint(websocket_connection)
        if fingerprint != CERTIFICATE_FINGERPRINT:
            self._logger.error(f"{HOST} presented certificate {fingerprint}, which does not match the pin. If Wisdom Capital has renewed, refresh CERTIFICATE_FINGERPRINT.")
            websocket_connection.close()
            return
        self._opened = True
        websocket_connection.send("2probe")

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

    def _on_close(self, websocket_connection, status_code, message):
        """
        Stops this connection's heartbeat and reports that the connection closed.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that closed.
            status_code (int | None): The close status.
            message (str | None): The close reason.

        Returns:
            None: This method returns nothing.
        """
        self._connection_closed.set()
        super()._on_close(websocket_connection, status_code, message)

    def _on_message(self, websocket_connection, message):
        """
        Handles Engine.IO control frames and hands on the orders and positions each socket.io event carries.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the frame arrived on.
            message (bytes | str): The frame.

        Returns:
            None: This method returns nothing.
        """
        if isinstance(message, (bytes, bytearray)):
            message = message.decode("utf-8", errors="replace")
        if message == "3probe":
            websocket_connection.send("5")
            self._transport.start_heartbeat(
                websocket_connection,
                self._connection_closed,
                self._heartbeat_seconds,
                self._stop,
                "wisdom_capital_order_updates_heartbeat",
            )
            self._logger.info("Joined the interactive namespace. Waiting for order and position updates.")
            return
        if message == "2":
            websocket_connection.send("3")
            return
        if not isinstance(message, str) or not message.startswith("42"):
            return

        try:
            event = json.loads(message[2:])
        except json.JSONDecodeError:
            return
        if not isinstance(event, list) or not event:
            return
        name = str(event[0]).lower()
        payload = None
        if len(event) > 1:
            payload = event[1]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                pass
        if name == "logout":
            self._logger.warning(f"Wisdom Capital logged this socket out: {json.dumps(payload)[:200]}. Reconnecting with the login now in force.")
            self._logged_out = True
            websocket_connection.close()
            return

        items = payload
        if not isinstance(payload, list):
            items = [payload]
        entries = []
        for item in items:
            if isinstance(item, dict):
                entries.append(item)
        received_at = datetime.now()

        if "position" in name:
            if entries:
                self._on_updates([], entries, received_at)
        elif "trade" in name:
            self._logger.debug("Trade event received; the matching order event carries the fill.")
        elif "order" in name or "interactive" in name:
            if entries:
                self._on_updates(entries, [], received_at)
        else:
            self._logger.info(f"Event {event[0]!r}: {json.dumps(payload)[:200]}")
