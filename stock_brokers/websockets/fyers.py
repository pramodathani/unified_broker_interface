"""
Fyers' two websockets: the HSM market feed and the account's order and position update stream.

**The login.**
`FyersSession` holds the `FyersAPI` both sockets read their credentials from, afresh on every connect, so a login made by any process is picked up.
`FyersAPI` logs in only when its probe raises, and Fyers can refuse a dead session inside an HTTP 200, so every login is confirmed against the profile endpoint and a refused profile raises.
The access token is a JWT: a token whose `exp` has passed is treated as a refused login without sending anything, because Fyers' edge bans addresses that keep sending refused requests.
The quote sockets log in again one at a time, and only when no other socket or process has already replaced the token that failed; the order socket logs in again whenever it is refused, without that check, as it always has.

**Quotes.**
`FyersQuotesSocket` speaks the binary protocol Fyers' SDK calls HSM, at `wss://socket.fyers.in/hsm/v1-5/prod`.
The feed is not authenticated with the access token but with the `hsm_key` claim inside it, sent in a binary frame after connecting.
Subscription is by HSM topic name, so each connect first resolves the symbols through `POST https://api-t1.fyers.in/data/symbol-token`, whose `validSymbol` maps each symbol to its fytoken.
The fytoken's first four digits name the exchange segment and the digits from the eleventh on the exchange token, giving `sf|nse_cm|3045` for `NSE:SBIN-EQ`; an index is `if|nse_cm|Nifty 50`, by the index names Fyers' SDK carries.
Once the authentication frame is acknowledged the socket selects full mode and subscribes the topic names, 1,500 a frame, and it acknowledges every `ack_count` data messages, the count the authentication response gives, as the SDK does.
The feed is incremental: a snapshot packet (type 83) names a topic and carries every field, followed by the price multiplier and precision and three strings; update packets (85, and 76 for lite) carry the topic id and positional values, where -2147483648 means "no value", read against the fixed field tables below.
Prices are scaled integers, divided by 10 to the precision times the multiplier.
A Cloudflare ban on the symbol lookup pauses the socket thirty minutes and a rate limit five, rather than logging in, because every refused request extends a ban; that pause is why the quote socket keeps a reconnect loop of its own.
Symbol lookup codes -8, -15, -16 and -17, or HTTP 401, mean the session is dead.

**Order updates.**
`FyersOrderUpdatesSocket` connects to `wss://socket.fyers.in/trade/v3` with an `authorization` header of the app id and access token joined by a colon, so a bad credential fails the HTTP upgrade itself.
Once open it sends `{"T": "SUB_ORD", "SLIST": ["orders", "positions"], "SUB_T": 1}`, Fyers answers with code 1605, and every change then arrives as JSON: `{"s": "ok", "orders": {...}}` for an order and `{"s": "ok", "positions": {...}}` for a position.
An error message carrying a session code closes the socket, after the message's orders and positions have been handed on.
Fyers answers its keepalive with a bare `ping` or `pong` rather than a frame.

Neither socket writes Redis.
The quotes socket hands each message's ticks to `on_ticks`, and the order socket hands each message's orders and positions to `on_updates`; the scripts in `bin/fyers/` do the writing.
"""

import base64
import json
import struct
import threading
import time
from datetime import datetime

from stock_brokers.websockets.base import BrokerWebsocket

FEED_URL = "wss://socket.fyers.in/hsm/v1-5/prod"
ORDER_UPDATES_URL = "wss://socket.fyers.in/trade/v3"
SYMBOL_TOKEN_URL = "https://api-t1.fyers.in/data/symbol-token"
PROFILE_URL = "https://api-t1.fyers.in/api/v3/profile"

SYMBOLS_PER_LOOKUP = 500
TOPICS_PER_SUBSCRIBE = 1500

SOURCE = "PythonSDK-3.0.9"
MODE = "P"
CHANNEL = 11

AUTH_RESPONSE = 1
ACKNOWLEDGE = 3
SUBSCRIBE = 4
DATAFEED_RESPONSE = 6
FULL_MODE = 12
SNAPSHOT = 83
UPDATE = 85
LITE = 76
NO_VALUE = -2147483648

EXCHANGE_SEGMENTS = {
    "1010": "nse_cm",
    "1011": "nse_fo",
    "1120": "mcx_fo",
    "1210": "bse_cm",
    "1012": "cde_fo",
    "1211": "bse_fo",
    "1212": "bcs_fo",
    "1020": "nse_com",
}

INDEX_TOPIC_NAMES = {
    "NSE:NIFTYINDIAMFG-INDEX": "NIFTY INDIA MFG",
    "NSE:NIFTY100ESG-INDEX": "NIFTY100 ESG",
    "NSE:NIFTYINDDIGITAL-INDEX": "NIFTY IND DIGITAL",
    "NSE:NIFTYMICROCAP250-INDEX": "NIFTY MICROCAP250",
    "NSE:NIFTYCONSRDURBL-INDEX": "NIFTY CONSR DURBL",
    "NSE:NIFTYHEALTHCARE-INDEX": "NIFTY HEALTHCARE",
    "NSE:NIFTYOILANDGAS-INDEX": "NIFTY OIL AND GAS",
    "NSE:NIFTY100ESGSECLDR-INDEX": "Nifty100ESGSecLdr",
    "NSE:NIFTY200MOMENTM30-INDEX": "Nifty200Momentm30",
    "NSE:NIFTYALPHALOWVOL-INDEX": "NIFTY AlphaLowVol",
    "NSE:NIFTY200QUALTY30-INDEX": "NIFTY200 QUALTY30",
    "NSE:NIFTYSMLCAP50-INDEX": "NIFTY SMLCAP 50",
    "NSE:MIDCPNIFTY-INDEX": "NIFTY MID SELECT",
    "NSE:NIFTYMIDCAP150-INDEX": "NIFTY MIDCAP 150",
    "NSE:NIFTY100 EQL WGT-INDEX": "NIFTY100 EQL Wgt",
    "NSE:NIFTY50 EQL WGT-INDEX": "NIFTY50 EQL Wgt",
    "NSE:NIFTYGSCOMPSITE-INDEX": "Nifty GS Compsite",
    "NSE:NIFTYGS1115YR-INDEX": "Nifty GS 11 15Yr",
    "NSE:NIFTYGS48YR-INDEX": "Nifty GS 4 8Yr",
    "NSE:NIFTYGS10YRCLN-INDEX": "Nifty GS 10Yr Cln",
    "NSE:NIFTYGS813YR-INDEX": "Nifty GS 8 13Yr",
    "NSE:NIFTYSMLCAP100-INDEX": "NIFTY SMLCAP 100",
    "NSE:NIFTYQUALITY30-INDEX": "NIFTY100 Qualty30",
    "NSE:NIFTYPVTBANK-INDEX": "Nifty Pvt Bank",
    "NSE:NIFTYPHARMA-INDEX": "Nifty Pharma",
    "NSE:NIFTYLARGEMID250-INDEX": "NIFTY LARGEMID250",
    "NSE:NIFTYGS15YRPLUS-INDEX": "Nifty GS 15YrPlus",
    "NSE:NIFTYPSUBANK-INDEX": "Nifty PSU Bank",
    "NSE:NIFTYSMLCAP250-INDEX": "NIFTY SMLCAP 250",
    "NSE:NIFTYENERGY-INDEX": "Nifty Energy",
    "NSE:NIFTYALPHA50-INDEX": "NIFTY Alpha 50",
    "NSE:NIFTYPSE-INDEX": "Nifty PSE",
    "NSE:NIFTYFINSRV2550-INDEX": "Nifty FinSrv25 50",
    "NSE:FINNIFTY-INDEX": "Nifty Fin Service",
    "NSE:NIFTYREALTY-INDEX": "Nifty Realty",
    "NSE:NIFTY500-INDEX": "Nifty 500",
    "NSE:NIFTY500MULTICAP-INDEX": "NIFTY500 MULTICAP",
    "NSE:NIFTYMIDCAP50-INDEX": "Nifty Midcap 50",
    "NSE:NIFTYTOTALMKT-INDEX": "NIFTY TOTAL MKT",
    "NSE:NIFTY50PR2XLEV-INDEX": "Nifty50 PR 2x Lev",
    "NSE:INDIAVIX-INDEX": "India VIX",
    "NSE:NIFTYDIVOPPS50-INDEX": "Nifty Div Opps 50",
    "NSE:NIFTYMNC-INDEX": "Nifty MNC",
    "NSE:NIFTY50VALUE20-INDEX": "Nifty50 Value 20",
    "NSE:NIFTY50-INDEX": "Nifty 50",
    "NSE:HANGSENG BEES-NAV-INDEX": "HangSeng BeES-NAV",
    "NSE:NIFTY100LIQ15-INDEX": "Nifty100 Liq 15",
    "NSE:NIFTY50TR2XLEV-INDEX": "Nifty50 TR 2x Lev",
    "NSE:NIFTY100-INDEX": "Nifty 100",
    "NSE:NIFTY100 LOWVOL30-INDEX": "NIFTY100 LowVol30",
    "NSE:NIFTYBANK-INDEX": "Nifty Bank",
    "NSE:NIFTYFMCG-INDEX": "Nifty FMCG",
    "NSE:NIFTYIT-INDEX": "Nifty IT",
    "NSE:NIFTYGS10YR-INDEX": "Nifty GS 10Yr",
    "NSE:NIFTYMIDCAP100-INDEX": "NIFTY MIDCAP 100",
    "NSE:NIFTYNEXT50-INDEX": "Nifty Next 50",
    "NSE:NIFTYNXT50-INDEX": "Nifty Next 50",
    "NSE:NIFTYM150QLTY50-INDEX": "NIFTY M150 QLTY50",
    "NSE:NIFTYSERVSECTOR-INDEX": "Nifty Serv Sector",
    "NSE:NIFTYMIDSML400-INDEX": "NIFTY MIDSML 400",
    "NSE:NIFTYAUTO-INDEX": "Nifty Auto",
    "NSE:NIFTYMETAL-INDEX": "Nifty Metal",
    "NSE:NIFTYINFRA-INDEX": "Nifty Infra",
    "NSE:NIFTYMEDIA-INDEX": "Nifty Media",
    "NSE:NIFTY50PR1XINV-INDEX": "Nifty50 PR 1x Inv",
    "NSE:NIFTY200-INDEX": "Nifty 200",
    "NSE:NIFTY50TR1XINV-INDEX": "Nifty50 TR 1x Inv",
    "NSE:NIFTYCPSE-INDEX": "Nifty CPSE",
    "NSE:NIFTYMIDLIQ15-INDEX": "Nifty Mid Liq 15",
    "NSE:NIFTYCOMMODITIES-INDEX": "Nifty Commodities",
    "NSE:NIFTYCONSUMPTION-INDEX": "Nifty Consumption",
    "NSE:NIFTY50DIVPOINT-INDEX": "Nifty50 Div Point",
    "NSE:NIFTYGROWSECT15-INDEX": "Nifty GrowSect 15",
    "BSE:100LARGECAPTMC-INDEX": "LCTMCI",
    "BSE:DFRG-INDEX": "DFRGRI",
    "BSE:QUALITY-INDEX": "BSEQUI",
    "BSE:DIVIDENDSTABILITY-INDEX": "BSEDSI",
    "BSE:250SMALLCAP-INDEX": "SML250",
    "BSE:150MIDCAP-INDEX": "MID150",
    "BSE:ESG100-INDEX": "ESG100",
    "BSE:SNXT50-INDEX": "SNXT50",
    "BSE:SNSX50-INDEX": "SNSX50",
    "BSE:UTILS-INDEX": "UTILS",
    "BSE:GREENEX-INDEX": "GREENX",
    "BSE:SENSEX-INDEX": "SENSEX",
    "BSE:REALTY-INDEX": "REALTY",
    "BSE:PRIVATEBANKS-INDEX": "BSEPBI",
    "BSE:CDGS-INDEX": "CDGS",
    "BSE:OILGAS-INDEX": "OILGAS",
    "BSE:ENERGY-INDEX": "ENERGY",
    "BSE:POWER-INDEX": "POWER",
    "BSE:500-INDEX": "BSE500",
    "BSE:100-INDEX": "BSE100",
    "BSE:PSU-INDEX": "BSEPSU",
    "BSE:HC-INDEX": "BSE HC",
    "BSE:400MIDSMALLCAP-INDEX": "MSL400",
    "BSE:BHRT22-INDEX": "BHRT22",
    "BSE:BANKEX-INDEX": "BANKEX",
    "BSE:ALLCAP-INDEX": "ALLCAP",
    "BSE:INFRA-INDEX": "INFRA",
    "BSE:CD-INDEX": "BSE CD",
    "BSE:MIDCAP-INDEX": "MIDCAP",
    "BSE:AUTO-INDEX": "AUTO",
    "BSE:BASMTR-INDEX": "BASMTR",
    "BSE:200-INDEX": "BSE200",
    "BSE:FIN-INDEX": "FIN",
    "BSE:CG-INDEX": "BSE CG",
    "BSE:ENHANCEDVALUE-INDEX": "BSEEVI",
    "BSE:TECK-INDEX": "TECK",
    "BSE:METAL-INDEX": "METAL",
    "BSE:CARBONEX-INDEX": "CARBON",
    "BSE:MIDSEL-INDEX": "MIDSEL",
    "BSE:SME IPO-INDEX": "SMEIPO",
    "BSE:MOMENTUM-INDEX": "BSEMOI",
    "BSE:TELCOM-INDEX": "TELCOM",
    "BSE:CPSE-INDEX": "CPSE",
    "BSE:250LARGEMIDCAP-INDEX": "LMI250",
    "BSE:SMLCAP-INDEX": "SMLCAP",
    "BSE:IT-INDEX": "BSE IT",
    "BSE:INDIAMANUFACTURING-INDEX": "MFG",
    "BSE:INDSTR-INDEX": "INDSTR",
    "BSE:LOWVOLATILITY-INDEX": "BSELVI",
    "BSE:LRGCAP-INDEX": "LRGCAP",
    "BSE:IPO-INDEX": "BSEIPO",
    "BSE:FMC-INDEX": "BSEFMC",
    "BSE:SMLSEL-INDEX": "SMLSEL",
    "NSE:NIFTYINDDEFENCE-INDEX": "Nifty Ind Defence",
    "NSE:NIFTYTATA25CAP-INDEX": "Nifty Tata 25 Cap",
    "NSE:NIFTYMIDSMLHLTH-INDEX": "Nifty MidSml Hlth",
    "NSE:NIFTYMULTIMFG-INDEX": "Nifty Multi Mfg",
    "NSE:NIFTYMULTIINFRA-INDEX": "Nifty Multi Infra",
    "NSE:BHARATBOND-APR30-INDEX": "BHARATBOND-APR30",
    "NSE:BHARATBOND-APR31-INDEX": "BHARATBOND-APR31",
    "NSE:BHARATBOND-APR32-INDEX": "BHARATBOND-APR32",
    "NSE:BHARATBOND-APR33-INDEX": "BHARATBOND-APR33",
    "NSE:NIFTYINDTOURISM-INDEX": "Nifty Ind Tourism",
    "NSE:NIFTYCAPITALMKT-INDEX": "Nifty Capital Mkt",
    "NSE:NIFTY500MOMENTM50-INDEX": "Nifty500Momentm50",
    "NSE:NIFTYMS400MQ100-INDEX": "NiftyMS400 MQ 100",
    "NSE:NIFTYSML250MQ100-INDEX": "NiftySml250MQ 100",
    "NSE:NIFTYTOP10EW-INDEX": "Nifty Top 10 EW",
    "NSE:NIFTYAQL30-INDEX": "Nifty AQL 30",
    "NSE:NIFTYAQLV30-INDEX": "Nifty AQLV 30",
    "NSE:NIFTYEV-INDEX": "Nifty EV",
    "NSE:NIFTYHIGHBETA50-INDEX": "Nifty HighBeta 50",
    "NSE:NIFTYNEWCONSUMP-INDEX": "Nifty New Consump",
    "NSE:NIFTYCORPMAATR-INDEX": "Nifty Corp MAATR",
    "NSE:NIFTYLOWVOL50-INDEX": "Nifty Low Vol 50",
    "NSE:NIFTYMOBILITY-INDEX": "Nifty Mobility",
    "NSE:NIFTYQLTYLV30-INDEX": "Nifty Qlty LV 30",
    "NSE:NIFTYSML250Q50-INDEX": "Nifty Sml250 Q50",
    "NSE:NIFTYTOP15EW-INDEX": "Nifty Top 15 EW",
    "NSE:NIFTY100ALPHA30-INDEX": "Nifty100 Alpha 30",
    "NSE:NIFTY100ENHESG-INDEX": "Nifty100 Enh ESG",
    "NSE:NIFTY200VALUE30-INDEX": "Nifty200 Value 30",
    "NSE:NIFTY500EW-INDEX": "Nifty500 EW",
    "NSE:NIFTYMULTIMQ50-INDEX": "Nifty Multi MQ 50",
    "NSE:NIFTY500VALUE50-INDEX": "Nifty500 Value 50",
    "NSE:NIFTYTOP20EW-INDEX": "Nifty Top 20 EW",
    "NSE:NIFTYCOREHOUSING-INDEX": "Nifty CoreHousing",
    "NSE:NIFTYFINSEREXBNK-INDEX": "Nifty FinSerExBnk",
    "NSE:NIFTYHOUSING-INDEX": "Nifty Housing",
    "NSE:NIFTYIPO-INDEX": "Nifty IPO",
    "NSE:NIFTYMSFINSERV-INDEX": "Nifty MS Fin Serv",
    "NSE:NIFTYMSINDCONS-INDEX": "Nifty MS Ind Cons",
    "NSE:NIFTYMSITTELCM-INDEX": "Nifty MS IT Telcm",
    "NSE:NIFTYNONCYCCONS-INDEX": "Nifty NonCyc Cons",
    "NSE:NIFTYRURAL-INDEX": "Nifty Rural",
    "NSE:NIFTYSHARIAH25-INDEX": "Nifty Shariah 25",
    "NSE:NIFTYTRANSLOGIS-INDEX": "Nifty Trans Logis",
    "NSE:NIFTY50SHARIAH-INDEX": "Nifty50 Shariah",
    "NSE:NIFTY500LMSEQL-INDEX": "Nifty500 LMS Eql",
    "NSE:NIFTY500SHARIAH-INDEX": "Nifty500 Shariah",
    "NSE:NIFTY500QLTY50-INDEX": "Nifty500 Qlty50",
    "NSE:NIFTY500LOWVOL50-INDEX": "Nifty500 LowVol50",
}

DATA_FIELDS = [
    "ltp",
    "vol_traded_today",
    "last_traded_time",
    "exch_feed_time",
    "bid_size",
    "ask_size",
    "bid_price",
    "ask_price",
    "last_traded_qty",
    "tot_buy_qty",
    "tot_sell_qty",
    "avg_trade_price",
    "OI",
    "low_price",
    "high_price",
    "Yhigh",
    "Ylow",
    "lower_ckt",
    "upper_ckt",
    "open_price",
    "prev_close_price",
    "type",
    "symbol",
]
INDEX_FIELDS = [
    "ltp",
    "prev_close_price",
    "exch_feed_time",
    "high_price",
    "low_price",
    "open_price",
    "type",
    "symbol",
]
LITE_FIELDS = [
    "ltp",
    "symbol",
    "type",
]
DEPTH_FIELDS = [
    "bid_price1",
    "bid_price2",
    "bid_price3",
    "bid_price4",
    "bid_price5",
    "ask_price1",
    "ask_price2",
    "ask_price3",
    "ask_price4",
    "ask_price5",
    "bid_size1",
    "bid_size2",
    "bid_size3",
    "bid_size4",
    "bid_size5",
    "ask_size1",
    "ask_size2",
    "ask_size3",
    "ask_size4",
    "ask_size5",
    "bid_order1",
    "bid_order2",
    "bid_order3",
    "bid_order4",
    "bid_order5",
    "ask_order1",
    "ask_order2",
    "ask_order3",
    "ask_order4",
    "ask_order5",
    "type",
    "symbol",
]

AUTHENTICATION_ERROR_CODES = {
    -8,
    -15,
    -16,
    -17,
}
AUTHENTICATION_HANDSHAKE_STATUSES = {
    401,
    403,
}

BLOCK_PAGE_MARKERS = (
    "error 1015",
    "error code: 1015",
    "banned you temporarily",
)
BLOCK_PAUSE_SECONDS = 30 * 60
THROTTLE_PAUSE_SECONDS = 5 * 60

SUBSCRIBE_CHANNELS = [
    "orders",
    "positions",
]
SUBSCRIBED_CODE = 1605

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class FyersRefusal(Exception):
    """
    Fyers refused a request, with its code and message.

    Attributes:
        code (int | str | None): Fyers' code, or the HTTP status.
        message (str): What Fyers said.
    """

    def __init__(self, code, message):
        """
        Keeps the code and the message.

        Args:
            code (int | str | None): Fyers' code, or the HTTP status.
            message (str): What Fyers said.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(code, message)
        self.code = code
        self.message = message


class FyersSession:
    """
    The Fyers login every socket authenticates with, confirmed against the profile and logged in again by one socket at a time.
    """

    def __init__(self, logger):
        """
        Constructs `FyersAPI`, which logs in when its probe raises, and confirms the session against the profile.

        Args:
            logger (logging.Logger): Where logins are reported.

        Returns:
            None: This method returns nothing.

        Raises:
            FyersRefusal: When the profile is refused.
            Exception: Whatever `FyersAPI` raises when it cannot log in.
        """
        from stock_brokers.api.fyers import FyersAPI

        self._api_class = FyersAPI
        self._logger = logger
        self._lock = threading.Lock()
        self._fyers = self._confirmed(FyersAPI())

    def credentials(self):
        """
        The app id and the access token in force now, which may be one another process has just obtained.

        Returns:
            tuple: The app id and the access token, either of which may be None.
        """
        login = self._fyers._current_login() or {}
        return self._fyers._settings.get("app_id"), login.get("access_token")

    def token_claims(self, access_token):
        """
        The claims inside a Fyers access token, a JWT.

        Args:
            access_token (str | None): The token.

        Returns:
            dict: The claims, or an empty dictionary when the token cannot be decoded.
        """
        try:
            return json.loads(base64.urlsafe_b64decode(str(access_token).split(".")[1] + "===").decode())
        except Exception:
            return {}

    def log_in_again(self, stale_token):
        """
        Logs in again and confirms the session, unless another socket or process already replaced the token that failed.

        Args:
            stale_token (str | None): The access token the failing connection used.

        Returns:
            None: This method returns nothing.

        Raises:
            FyersRefusal: When the new session's profile is refused.
            Exception: Whatever `FyersAPI` raises when it cannot log in.
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
            FyersRefusal: When the new session's profile is refused.
            Exception: Whatever `FyersAPI` raises when it cannot log in.
        """
        with self._lock:
            self._log_in()

    def _log_in(self):
        """
        Logs in by constructing `FyersAPI` again and confirms it; the caller holds the lock.

        Returns:
            None: This method returns nothing.

        Raises:
            FyersRefusal: When the new session's profile is refused.
            Exception: Whatever `FyersAPI` raises when it cannot log in.
        """
        self._logger.warning("Logging in to Fyers again.")
        self._fyers = self._confirmed(self._api_class())

    def _confirmed(self, fyers):
        """
        Checks that the profile is served, since a constructor that returned is no proof of a session.

        Args:
            fyers (FyersAPI): The API object to check.

        Returns:
            FyersAPI: The same object.

        Raises:
            FyersRefusal: When the profile is refused.
        """
        body = (fyers.get(url=PROFILE_URL, timeout=30) or {}).get("data")
        if not isinstance(body, dict) or body.get("s") not in (None, "ok"):
            code = None
            if isinstance(body, dict):
                code = body.get("code")
            raise FyersRefusal(code, f"the profile was refused: {str(body)[:200]}")
        return fyers


class FyersHsmFrames:
    """
    Builds and reads the HSM binary frames of Fyers' market feed.
    """

    def auth_frame(self, hsm_key):
        """
        The frame that authenticates the feed with the hsm key.

        Args:
            hsm_key (str): The `hsm_key` claim of the access token.

        Returns:
            bytes: The frame.
        """
        frame = bytearray()
        frame.extend(struct.pack("!H", 18 + len(hsm_key) + len(SOURCE) - 2))
        frame.extend(bytes([1, 4]))
        frame.extend(bytes([1]) + struct.pack("!H", len(hsm_key)) + hsm_key.encode())
        frame.extend(bytes([2]) + struct.pack("!H", 1) + MODE.encode())
        frame.extend(bytes([3]) + struct.pack("!H", 1) + bytes([1]))
        frame.extend(bytes([4]) + struct.pack("!H", len(SOURCE)) + SOURCE.encode())
        return bytes(frame)

    def auth_response(self, data):
        """
        Reads an authentication response: a `K` in its first field on success, then the acknowledgement count.

        Args:
            data (bytes): The response.

        Returns:
            tuple: Whether the feed was accepted, and how many data messages to acknowledge at a time.
        """
        try:
            length = struct.unpack("!H", data[5:7])[0]
            accepted = data[7:7 + length] == b"K"
            offset = 7 + length + 1
            length = struct.unpack("!H", data[offset:offset + 2])[0]
            ack_count = 0
            if length >= 4:
                ack_count = struct.unpack(">I", data[offset + 2:offset + 6])[0]
            return accepted, ack_count
        except struct.error:
            return False, 0

    def full_mode_frame(self):
        """
        The frame that puts the channel in full mode, so data packets carry every field.

        Returns:
            bytes: The frame.
        """
        frame = bytearray(struct.pack(">H", 0))
        frame.extend(bytes([FULL_MODE, 2]))
        frame.extend(bytes([1]) + struct.pack(">H", 8) + struct.pack(">Q", 1 << CHANNEL))
        frame.extend(bytes([2]) + struct.pack(">H", 1) + bytes([70]))
        return bytes(frame)

    def subscribe_frame(self, topics):
        """
        The frame that subscribes HSM topic names on the channel.

        Args:
            topics (list[str]): The topic names, such as `sf|nse_cm|3045`, at most 1,500 of them.

        Returns:
            bytes: The frame.
        """
        scrips = bytearray(struct.pack(">H", len(topics)))
        for topic in topics:
            encoded = topic.encode("ascii")
            scrips.extend(bytes([len(encoded)]) + encoded)
        frame = bytearray(struct.pack(">H", 18 + len(scrips)))
        frame.extend(bytes([SUBSCRIBE, 2]))
        frame.extend(bytes([1]) + struct.pack(">H", len(scrips)) + scrips)
        frame.extend(bytes([2]) + struct.pack(">H", 1) + bytes([CHANNEL]))
        return bytes(frame)

    def acknowledge_frame(self, message_number):
        """
        The frame that acknowledges data messages up to a message number.

        Args:
            message_number (int): The number in a data message's header.

        Returns:
            bytes: The frame.
        """
        return struct.pack(">HBBBHI", 9, ACKNOWLEDGE, 1, 1, 4, message_number)

    def topic_name(self, symbol, fytoken):
        """
        The HSM topic name of a Fyers symbol.

        Args:
            symbol (str): The Fyers symbol, such as `NSE:SBIN-EQ` or `NSE:NIFTY50-INDEX`.
            fytoken (str): The symbol's fytoken from the symbol-token endpoint.

        Returns:
            str | None: The topic name, or None when its segment is not one the feed carries.
        """
        segment = EXCHANGE_SEGMENTS.get(fytoken[:4])
        if segment is None:
            return None
        if symbol.endswith("-INDEX"):
            index_name = INDEX_TOPIC_NAMES.get(symbol) or symbol.split(":", 1)[-1].rsplit("-", 1)[0]
            return f"if|{segment}|{index_name}"
        return f"sf|{segment}|{fytoken[10:]}"

    def price_divisor(self, state):
        """
        What an instrument's scaled integer prices are divided by.

        Args:
            state (dict): The instrument's merged field state.

        Returns:
            int: 10 to its precision times its multiplier, from its snapshot, or 100 when no snapshot has said.
        """
        precision = state.get("precision")
        multiplier = state.get("multiplier")
        if precision is None or not multiplier:
            return 100
        return (10 ** precision) * multiplier

    def fields_for(self, topic_name, field_count):
        """
        The field table a packet's positional values are read against.

        Args:
            topic_name (str): The topic name its snapshot gave, which encodes the feed kind.
            field_count (int): The number of values in the packet.

        Returns:
            list[str]: The field names.
        """
        if topic_name.startswith("dp"):
            return DEPTH_FIELDS
        if topic_name.startswith("if"):
            return INDEX_FIELDS
        if field_count <= len(LITE_FIELDS):
            return LITE_FIELDS
        return DATA_FIELDS


class FyersQuotesSocket(BrokerWebsocket):
    """
    One Fyers HSM market feed websocket for a batch of symbols.
    """

    def __init__(self, name, symbols, session, on_ticks, logger):
        """
        Sets up a socket for one batch of symbols.

        Args:
            name (str): The connection's name, for the log.
            symbols (list[str]): The batch of Fyers symbols, which are also the ticks' `id`.
            session (FyersSession): The shared login.
            on_ticks (callable): Called with each data message's list of ticks that carry a price or a book, on this socket's thread.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(name, logger)
        self._symbols = symbols
        self._session = session
        self._on_ticks = on_ticks
        self._frames = FyersHsmFrames()
        self._token = None
        self._hsm_key = None
        self._resolved = {}
        self._topics = {}
        self._state = {}
        self._ack_count = 0
        self._since_ack = 0
        self._pause_seconds = 0

    def run_forever(self):
        """
        Connects, and reconnects with backoff, until closed or unable to recover, pausing instead of logging in after a ban or a rate limit.

        This is `BrokerWebsocket.run_forever` with one step added: a connect that ended in a Cloudflare ban or a rate limit waits the pause out and connects again, without counting a failure or logging in, since a login would only extend a ban.

        Returns:
            None: This method returns nothing. `gave_up` says whether the socket stopped because it could not recover.
        """
        backoff = self.MIN_BACKOFF_SECONDS
        failed_connects = 0
        logged_in_again = False
        while not self._stop.is_set():
            self._opened = False
            self._authentication_rejected = False
            self._pause_seconds = 0
            try:
                self._connect()
            except Exception as exception:
                self._logger.error(f"{self.name} connection failed: {type(exception).__name__}: {exception}")
            if self._stop.is_set():
                break

            if self._pause_seconds:
                self._stop.wait(self._pause_seconds)
                continue

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

    def _connect(self):
        """
        Checks the token, resolves the symbols to topics, then opens the websocket and blocks until it closes.

        Returns:
            None: This method returns nothing.

        Raises:
            FyersRefusal: When no symbol resolves to a topic, or the symbol lookup fails for a reason other than the session, a ban or a limit.
        """
        import websocket

        app_id, self._token = self._session.credentials()
        claims = self._session.token_claims(self._token)
        if claims.get("exp", 0) <= time.time() or "hsm_key" not in claims:
            self._logger.warning(f"{self.name}: the Fyers access token has expired or carries no hsm_key.")
            self._authentication_rejected = True
            return
        self._hsm_key = claims["hsm_key"]

        try:
            self._resolved = self._resolve_symbols(app_id, self._token)
        except Exception as exception:
            if self._is_block(exception):
                self._logger.error(f"{self.name}: Cloudflare is blocking Fyers requests, pausing {BLOCK_PAUSE_SECONDS}s: {str(exception)[:160]}")
                self._pause_seconds = BLOCK_PAUSE_SECONDS
            elif self._is_throttle(exception):
                self._logger.warning(f"{self.name}: Fyers rate limited the symbol lookup, pausing {THROTTLE_PAUSE_SECONDS}s.")
                self._pause_seconds = THROTTLE_PAUSE_SECONDS
            elif self._is_authentication_error(exception):
                self._logger.warning(f"{self.name}: Fyers refused the session on the symbol lookup: {exception}")
                self._authentication_rejected = True
            else:
                raise
            return
        resolved_symbols = set(self._resolved.values())
        unresolved = []
        for symbol in self._symbols:
            if symbol not in resolved_symbols:
                unresolved.append(symbol)
        if unresolved:
            more = ""
            if len(unresolved) > 20:
                more = " ..."
            self._logger.warning(f"{self.name}: {len(unresolved)} symbol(s) did not resolve and are not subscribed: {', '.join(unresolved[:20])}{more}")
        if not self._resolved:
            raise FyersRefusal(None, "no symbol resolved to a topic")

        self._topics = {}
        self._state = {}
        self._ack_count = 0
        self._since_ack = 0
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

    def _resolve_symbols(self, app_id, token):
        """
        The Fyers symbol of each HSM topic name, from the symbol-token endpoint, five hundred symbols a request.

        Args:
            app_id (str): The app id the request is authorized with.
            token (str): The access token the request is authorized with.

        Returns:
            dict[str, str]: Each topic name to its symbol; a symbol listed as invalid, or whose segment the feed does not carry, is left out.

        Raises:
            FyersRefusal: When the endpoint answers with an error or something that is not JSON.
        """
        import requests

        headers = {
            "Authorization": f"{app_id}:{token}",
            "Content-Type": "application/json",
        }
        resolved = {}
        for start in range(0, len(self._symbols), SYMBOLS_PER_LOOKUP):
            response = requests.post(SYMBOL_TOKEN_URL, headers=headers, json={"symbols": self._symbols[start:start + SYMBOLS_PER_LOOKUP]}, timeout=60)
            try:
                body = response.json()
            except ValueError:
                raise FyersRefusal(response.status_code, response.text[:300])
            if response.status_code >= 300 or body.get("s") == "error":
                code = body.get("code")
                if code is None:
                    code = response.status_code
                raise FyersRefusal(code, str(body.get("message") or body)[:300])
            for symbol, fytoken in (body.get("validSymbol") or {}).items():
                topic = self._frames.topic_name(symbol, str(fytoken))
                if topic is not None:
                    resolved[topic] = symbol
        return resolved

    def _refusal_code(self, exception):
        """
        The numeric code a refusal carries.

        Args:
            exception (Exception): The refusal.

        Returns:
            int | None: The code, or None.
        """
        try:
            return int(getattr(exception, "code", None))
        except (TypeError, ValueError):
            return None

    def _is_block(self, exception):
        """
        Whether a refusal is Cloudflare's address ban rather than anything Fyers itself said.

        Args:
            exception (Exception): The refusal.

        Returns:
            bool: True for a ban.
        """
        lowered = str(exception).lower()
        for marker in BLOCK_PAGE_MARKERS:
            if marker in lowered:
                return True
        return self._refusal_code(exception) == 429 and "cloudflare" in lowered

    def _is_throttle(self, exception):
        """
        Whether a refusal is a rate limit.

        Args:
            exception (Exception): The refusal.

        Returns:
            bool: True for a rate limit.
        """
        lowered = str(exception).lower()
        return self._refusal_code(exception) == 429 or "too many requests" in lowered or "rate limit" in lowered

    def _is_authentication_error(self, exception):
        """
        Whether Fyers refused the request because the session is dead, and not for a ban or a limit.

        Args:
            exception (Exception): The refusal.

        Returns:
            bool: True for a dead session.
        """
        if self._is_block(exception) or self._is_throttle(exception):
            return False
        code = self._refusal_code(exception)
        return code in AUTHENTICATION_ERROR_CODES or code == 401

    def _log_in_again(self):
        """
        Logs in again through the shared session, which skips the login when the token was already replaced.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again(self._token)

    def _on_open(self, websocket_connection):
        """
        Authenticates with the hsm key; the subscription waits for the acknowledgement.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        websocket_connection.send(self._frames.auth_frame(self._hsm_key), opcode=0x2)
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
        Handles the acknowledgements, and hands on the ticks of each instrument a data message updated.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The message.

        Returns:
            None: This method returns nothing.
        """
        if not isinstance(message, (bytes, bytearray)) or len(message) < 3:
            return
        data = bytes(message)
        response_type = data[2]
        if response_type == AUTH_RESPONSE:
            accepted, self._ack_count = self._frames.auth_response(data)
            if not accepted:
                self._logger.warning(f"{self.name}: Fyers refused the feed authentication.")
                self._authentication_rejected = True
                websocket_connection.close()
                return
            websocket_connection.send(self._frames.full_mode_frame(), opcode=0x2)
            topics = list(self._resolved)
            for start in range(0, len(topics), TOPICS_PER_SUBSCRIBE):
                websocket_connection.send(self._frames.subscribe_frame(topics[start:start + TOPICS_PER_SUBSCRIBE]), opcode=0x2)
            self._logger.info(f"{self.name} authenticated and subscribed to {len(self._resolved)} instrument(s).")
            return
        if response_type == SUBSCRIBE:
            if len(data) > 7 and data[7:8] == b"K":
                self._logger.info(f"{self.name}: subscription acknowledged.")
            else:
                self._logger.error(f"{self.name}: Fyers refused the subscription.")
            return
        if response_type != DATAFEED_RESPONSE:
            return

        if self._ack_count > 0 and len(data) >= 7:
            self._since_ack = self._since_ack + 1
            if self._since_ack >= self._ack_count:
                websocket_connection.send(self._frames.acknowledge_frame(struct.unpack(">I", data[3:7])[0]), opcode=0x2)
                self._since_ack = 0

        ticks = []
        for symbol, state in self._parse_feed(data).items():
            tick = self._build_tick(symbol, state, self._frames.price_divisor(state))
            if tick["last_price"] is not None or tick["depth"]["buy"] or tick["depth"]["sell"]:
                ticks.append(tick)
        if ticks:
            self._on_ticks(ticks)

    def _parse_feed(self, data):
        """
        Merges a data feed response into the per-instrument state.

        Args:
            data (bytes): The data feed response.

        Returns:
            dict[str, dict]: The state of each instrument the response touched, by symbol.
        """
        if len(data) < 9:
            return {}
        updated = {}
        scrip_count = struct.unpack("!H", data[7:9])[0]
        offset = 9
        for _ in range(scrip_count):
            if offset + 1 > len(data):
                break
            packet_type = data[offset]
            offset = offset + 1

            if packet_type == SNAPSHOT:
                if offset + 3 > len(data):
                    break
                topic_id = struct.unpack("H", data[offset:offset + 2])[0]
                name_length = data[offset + 2]
                offset = offset + 3
                topic_name = data[offset:offset + name_length].decode("utf-8", errors="replace")
                offset = offset + name_length
                if offset >= len(data):
                    break
                field_count = data[offset]
                offset = offset + 1
                symbol = self._resolved.get(topic_name)
                self._topics[topic_id] = (symbol, topic_name)
            elif packet_type in (UPDATE, LITE):
                if offset + 3 > len(data):
                    break
                topic_id = struct.unpack("H", data[offset:offset + 2])[0]
                field_count = data[offset + 2]
                offset = offset + 3
                symbol, topic_name = self._topics.get(topic_id, (None, ""))
            else:
                break

            state = {}
            if symbol:
                state = self._state.setdefault(symbol, {})
            fields = self._frames.fields_for(topic_name, field_count)
            for index in range(field_count):
                if offset + 4 > len(data):
                    break
                value = struct.unpack(">i", data[offset:offset + 4])[0]
                offset = offset + 4
                if value != NO_VALUE and index < len(fields):
                    state[fields[index]] = value
            if packet_type == SNAPSHOT:
                if offset + 5 > len(data):
                    break
                state["multiplier"] = struct.unpack(">H", data[offset + 2:offset + 4])[0]
                state["precision"] = data[offset + 4]
                offset = offset + 5
                for _ in range(3):
                    if offset >= len(data):
                        break
                    offset = offset + 1 + data[offset]
            if symbol:
                updated[symbol] = state
        return updated

    def _build_tick(self, symbol, state, divisor):
        """
        Builds a normalized tick from an instrument's merged field state.

        Args:
            symbol (str): The Fyers symbol.
            state (dict): The merged field state.
            divisor (int): What turns Fyers' scaled integers into rupees.

        Returns:
            dict: The tick.
        """
        depth = {
            "buy": [],
            "sell": [],
        }
        for level in range(1, 6):
            if state.get(f"bid_price{level}") is not None:
                depth["buy"].append({
                    "quantity": state.get(f"bid_size{level}"),
                    "price": state[f"bid_price{level}"] / divisor,
                    "orders": state.get(f"bid_order{level}"),
                })
            if state.get(f"ask_price{level}") is not None:
                depth["sell"].append({
                    "quantity": state.get(f"ask_size{level}"),
                    "price": state[f"ask_price{level}"] / divisor,
                    "orders": state.get(f"ask_order{level}"),
                })
        if not depth["buy"] and state.get("bid_price"):
            depth["buy"].append({
                "quantity": state.get("bid_size"),
                "price": state["bid_price"] / divisor,
                "orders": None,
            })
        if not depth["sell"] and state.get("ask_price"):
            depth["sell"].append({
                "quantity": state.get("ask_size"),
                "price": state["ask_price"] / divisor,
                "orders": None,
            })

        last_price = self._price(state, "ltp", divisor)
        close = self._price(state, "prev_close_price", divisor)
        exchange = None
        if ":" in symbol:
            exchange = symbol.split(":", 1)[0]
        mode = "quote"
        if depth["buy"] or depth["sell"]:
            mode = "full"
        change = None
        if last_price is not None and close:
            change = (last_price - close) * 100 / close
        return {
            "id": symbol,
            "broker": "fyers",
            "instrument_token": symbol,
            "exchange": exchange,
            "mode": mode,
            "last_price": last_price,
            "last_quantity": state.get("last_traded_qty"),
            "average_price": self._price(state, "avg_trade_price", divisor),
            "volume": state.get("vol_traded_today"),
            "buy_quantity": state.get("tot_buy_qty"),
            "sell_quantity": state.get("tot_sell_qty"),
            "ohlc": {
                "open": self._price(state, "open_price", divisor),
                "high": self._price(state, "high_price", divisor),
                "low": self._price(state, "low_price", divisor),
                "close": close,
            },
            "change": change,
            "oi": state.get("OI"),
            "oi_day_high": None,
            "oi_day_low": None,
            "last_trade_time": state.get("last_traded_time"),
            "exchange_timestamp": state.get("exch_feed_time"),
            "depth": depth,
            "received_at": time.time(),
        }

    def _price(self, state, key, divisor):
        """
        A scaled integer price from the state in rupees.

        Args:
            state (dict): The merged field state.
            key (str): The field.
            divisor (int): The scale.

        Returns:
            float | None: The price, or None when the field is missing.
        """
        if state.get(key) is None:
            return None
        return state[key] / divisor


class FyersOrderUpdatesSocket(BrokerWebsocket):
    """
    Fyers' order and position update websocket, authenticated in its handshake.
    """

    def __init__(self, session, on_updates, logger):
        """
        Sets up the order updates socket.

        Args:
            session (FyersSession): The login.
            on_updates (callable): Called on this socket's thread with a message's orders and positions, each a list of Fyers' objects exactly as sent, and the `datetime` the message was received.
            logger (logging.Logger): Where the connection reports.

        Returns:
            None: This method returns nothing.
        """
        super().__init__("Order updates socket", logger)
        self._session = session
        self._on_updates = on_updates

    def _connect(self):
        """
        Opens the websocket with the token in force now, authenticated in the handshake, and blocks until it closes.

        Returns:
            None: This method returns nothing.
        """
        import websocket

        app_id, token = self._session.credentials()
        if self._session.token_claims(token).get("exp", 0) <= time.time():
            self._logger.warning("The Fyers access token has expired.")
            self._authentication_rejected = True
            return
        self._websocket_application = websocket.WebSocketApp(
            ORDER_UPDATES_URL,
            header={"authorization": f"{app_id}:{token}"},
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
        Logs in again and confirms the session, without checking whether another process already replaced the token.

        Returns:
            None: This method returns nothing.
        """
        self._session.log_in_again_without_checking()

    def _on_open(self, websocket_connection):
        """
        Subscribes to orders and positions; the session was authenticated by the handshake.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that opened.

        Returns:
            None: This method returns nothing.
        """
        self._opened = True
        websocket_connection.send(json.dumps({"T": "SUB_ORD", "SLIST": SUBSCRIBE_CHANNELS, "SUB_T": 1}))
        self._logger.info(f"{self.name} opened and subscribed to {', '.join(SUBSCRIBE_CHANNELS)}.")

    def _on_error(self, websocket_connection, error):
        """
        Notes a refused handshake and reports the error.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection that failed.
            error (Exception): The error, which carries `status_code` when the handshake was refused.

        Returns:
            None: This method returns nothing.
        """
        if getattr(error, "status_code", None) in AUTHENTICATION_HANDSHAKE_STATUSES:
            self._authentication_rejected = True
        self._logger.error(f"Order updates error: {error}")

    def _on_message(self, websocket_connection, message):
        """
        Hands a message's orders and positions on, then closes the socket if the message said the session is dead.

        Args:
            websocket_connection (websocket.WebSocketApp): The connection the message arrived on.
            message (bytes | str): The message.

        Returns:
            None: This method returns nothing.
        """
        received_at = datetime.now()
        orders, positions = self._parse(message)
        if orders or positions:
            self._on_updates(orders, positions, received_at)
        if self._authentication_rejected:
            websocket_connection.close()

    def _parse(self, message):
        """
        The orders and positions a message carries, acting on error and subscription messages.

        Args:
            message (bytes | str): The message.

        Returns:
            tuple: The orders and the positions, each a list of Fyers' objects in arrival order.
        """
        if isinstance(message, (bytes, bytearray)):
            message = bytes(message).decode("utf-8", errors="replace")
        if not isinstance(message, str) or message.strip() in ("", "ping", "pong"):
            return [], []
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self._logger.debug(f"Ignoring a frame that is not JSON: {message[:160]}")
            return [], []

        entries = payload
        if not isinstance(payload, list):
            entries = [payload]
        orders = []
        positions = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("s") == "error":
                try:
                    code = int(entry.get("code"))
                except (TypeError, ValueError):
                    code = None
                if code in AUTHENTICATION_ERROR_CODES:
                    self._authentication_rejected = True
                self._logger.error(f"Fyers reported an error: {entry.get('message') or entry}")
                continue
            if entry.get("code") == SUBSCRIBED_CODE:
                self._logger.info(f"Fyers: {entry.get('message')}.")
                continue

            order = entry.get("orders")
            position = entry.get("positions")
            if isinstance(order, dict) and self._has_text(order.get("id")):
                orders.append(order)
            elif isinstance(position, dict) and self._has_text(position.get("symbol")):
                positions.append(position)
            elif "trades" not in entry:
                self._logger.info(f"Ignoring a message: {json.dumps(entry)[:200]}")
        return orders, positions

    def _has_text(self, value):
        """
        Whether a field holds something other than a blank or an `NA` placeholder.

        Args:
            value (object): The field.

        Returns:
            bool: True when it holds a value.
        """
        return value is not None and str(value).strip() not in ("", "NA")
