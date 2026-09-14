"""
What a broker's positions module provides, and the position every module builds.

A module makes one call to its broker's positions endpoint - two for a broker that reports the day basis
separately - and turns each row into a position. The service resolves the position to an instrument from
its token and venue, merges it with the same instrument and product held elsewhere, and prices it.

**Venue.** A broker names where a position trades in its own codes - `NFO`, `NSE_FNO`, `NSEFO`, `nse_fo`
- and every one of them says both an exchange and a kind of instrument, cash, derivative or currency
derivative. The kind matters, because a token is only unique within one of the exchange's scrip files:
NSE cash token 2885 and NFO token 2885 are different instruments. `venue` reads any of those codes into
the canonical exchange and the kind, and the service resolves the token only among that kind's segments.

**Quantities** are units, signed net quantity positive for long and negative for short. Buy and sell
values are totals, so they add across brokers; a broker that reports average prices has its values
worked out from them. Profit is the broker's own, since only the broker applies the contract's multiplier.
"""

from unified_broker_interface.utilities.broker_funds.base import number
from unified_broker_interface.utilities.broker_holdings.base import price

# Broker venue codes, upper-cased, to the canonical exchange and the kind of instrument traded there.
VENUES = {
    "NSE": ("nse", "cash"), "BSE": ("bse", "cash"),
    "NFO": ("nse", "derivative"), "BFO": ("bse", "derivative"),
    "CDS": ("nse", "currency"), "BCD": ("bse", "currency"),
    "MCX": ("mcx", "commodity"), "NCX": ("ncdex", "commodity"), "NCDEX": ("ncdex", "commodity"),
    "NSE_EQ": ("nse", "cash"), "BSE_EQ": ("bse", "cash"),
    "NSE_FNO": ("nse", "derivative"), "BSE_FNO": ("bse", "derivative"),
    "NSE_CURRENCY": ("nse", "currency"), "BSE_CURRENCY": ("bse", "currency"),
    "MCX_COMM": ("mcx", "commodity"),
    "NSECM": ("nse", "cash"), "BSECM": ("bse", "cash"),
    "NSEFO": ("nse", "derivative"), "BSEFO": ("bse", "derivative"),
    "NSECD": ("nse", "currency"), "BSECD": ("bse", "currency"),
    "NSECO": ("nse", "commodity"), "MCXFO": ("mcx", "commodity"),
    "NSE_CM": ("nse", "cash"), "BSE_CM": ("bse", "cash"),
    "NSE_FO": ("nse", "derivative"), "BSE_FO": ("bse", "derivative"),
    "CDE_FO": ("nse", "currency"), "MCX_FO": ("mcx", "commodity"), "NSE_COM": ("nse", "commodity"),
}

# Broker product codes, upper-cased, to the product the API answers with.
PRODUCTS = {
    "CNC": "delivery", "C": "delivery", "DELIVERY": "delivery",
    "MIS": "intraday", "I": "intraday", "INTRA": "intraday", "INTRADAY": "intraday",
    "NRML": "carry", "M": "carry", "MARGIN": "carry", "NORMAL": "carry",
    "MTF": "margin_trading",
    "CO": "cover", "H": "cover", "BO": "bracket", "B": "bracket",
}

class PositionsUnavailable(Exception):
    """
    The broker answered, but not with positions - an error carried in a successful response, or a body of
    the wrong shape.
    """

def venue(value):
    """
    A broker's venue code as `(exchange, kind)`, or `(None, None)` when it is not one this API knows.

    `kind` is `cash`, `derivative`, `currency` or `commodity`.

    - `value` is the broker's exchange or exchange segment code.
    """
    return VENUES.get(str(value or "").strip().upper(), (None, None))

def product(value):
    """
    A broker's product code as `delivery`, `intraday`, `carry`, `margin_trading`, `cover` or `bracket`, or the
    code itself, lower-cased, when it is not one this API knows.

    - `value` is the broker's product code.
    """
    text = str(value or "").strip()
    return PRODUCTS.get(text.upper().replace("-", ""), text.lower() or None)

def position(broker_token=None, exchange=None, kind=None, symbol=None, product_code=None, quantity=0.0,
             buy_quantity=0.0, buy_value=0.0, sell_quantity=0.0, sell_value=0.0, realized=0.0, unrealized=0.0,
             last_price=None, close_price=None):
    """
    One position at one broker.

    - `broker_token` is the broker's own token for the instrument, as unified.broker_mappings stores it.
    - `exchange` and `kind` are the position's venue, from `venue`.
    - `symbol` is the broker's own trading symbol, reported when the instrument does not resolve.
    - `product_code` is the broker's product code, read through `product`.
    - `quantity` is the signed net quantity.
    - `buy_quantity`, `buy_value`, `sell_quantity` and `sell_value` are what was bought and sold, in total.
    - `realized` and `unrealized` are the broker's own profit.
    - `last_price` and `close_price` are the broker's own last price and previous close, or None.
    """
    return {
        "broker_token": None if broker_token in (None, "", 0, "0") else str(broker_token),
        "exchange": exchange,
        "kind": kind,
        "symbol": symbol or None,
        "product": product(product_code),
        "quantity": number(quantity),
        "buy_quantity": number(buy_quantity),
        "buy_value": number(buy_value),
        "sell_quantity": number(sell_quantity),
        "sell_value": number(sell_value),
        "realized": number(realized),
        "unrealized": number(unrealized),
        "last_price": price(last_price),
        "close_price": price(close_price),
    }

class BrokerPositionsSource:
    """
    Reads one broker's positions from its REST API.

    Attributes:
        BROKER_NAME (str): The broker, as named in the `settings` collection and unified.broker_mappings.
        TIMEOUT_SECONDS (float): How long the broker may take to connect, and then to send each part of
            its answer, before a call is abandoned.
    """

    BROKER_NAME = None
    TIMEOUT_SECONDS = 5

    def fetch(self, client):
        """
        The broker's positions, as `{"net": data, "day": data or None}`.

        `day` is None for a broker that reports no separate day basis.

        - `client` is the broker's API client, whose `get`/`post` carry the session.

        Raises `PositionsUnavailable` when the broker answered without positions, and lets the API client's
        own exceptions through. An account with no positions is an empty answer, not an error.
        """
        raise NotImplementedError

    def normalize(self, data):
        """
        The positions in one basis of what `fetch` returned, as a list of `position` dicts.

        - `data` is the `net` or `day` value `fetch` returned.
        """
        raise NotImplementedError

    def is_authentication_error(self, exception):
        """
        Whether an exception means the session is dead, so logging in again is the remedy.

        - `exception` is what `fetch` raised.
        """
        raise NotImplementedError
