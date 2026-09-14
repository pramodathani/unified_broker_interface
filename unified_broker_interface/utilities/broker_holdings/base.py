"""
What a broker's holdings module provides, and the holding every module builds.

A module makes one call to its broker's holdings endpoint and turns each row into a holding. The service
resolves the holding to an instrument from its token and exchange - or from its symbol when the broker
sends no token - merges it with the same instrument held elsewhere, and prices it.

**Quantity is everything held.** Several brokers split a holding into buckets - settled, bought and not yet
settled (T1), funded by the margin trading facility - and a holding's quantity is all of them, with its
invested value the cost of each bucket at that bucket's own average price. Reading only one bucket is how a
stock bought yesterday goes missing until it settles.

Numbers go through `number`, which reads a missing or non-numeric field as zero; prices go through
`price`, which reads one as None, because a missing price must stay unknown rather than value a holding
at zero.
"""

from unified_broker_interface.utilities.broker_funds.base import number

class HoldingsUnavailable(Exception):
    """
    The broker answered, but not with holdings - an error carried in a successful response, or a body of
    the wrong shape.
    """

def price(value):
    """
    A broker's price as a float, or None when it is missing, not a number, or zero.

    Brokers send zero for a price they do not have, and no listed security trades at zero.

    - `value` is the field as the broker sent it.
    """
    parsed = number(value)
    return parsed if parsed else None

def canonical_exchange(value):
    """
    A broker's exchange, `NSE` or `nse_cm` or `BSE`, as the canonical `nse` or `bse`, or None.

    - `value` is the broker's exchange or exchange segment.
    """
    text = str(value or "").strip().lower()
    for exchange in ("nse", "bse"):
        if text == exchange or text.startswith(f"{exchange}_"):
            return exchange
    return None

def holding(broker_token=None, exchange=None, isin=None, symbol=None, quantity=0.0, invested_value=0.0,
            collateral_quantity=0.0, last_price=None, close_price=None):
    """
    One holding at one broker.

    - `broker_token` is the broker's own token for the instrument, as unified.broker_mappings stores it,
      or None when the broker sends none.
    - `exchange` is the canonical exchange the token belongs to, or None when the broker does not say.
    - `isin` is the ISIN, or None when the broker sends none.
    - `symbol` is the broker's own trading symbol, reported when the instrument does not resolve.
    - `quantity` is every share held, across the broker's buckets.
    - `invested_value` is what the quantity cost.
    - `collateral_quantity` is the quantity pledged as collateral.
    - `last_price` is the broker's own last price, or None.
    - `close_price` is the broker's own previous close, or None.
    """
    return {
        "broker_token": None if broker_token in (None, "", 0, "0") else str(broker_token),
        "exchange": exchange,
        "isin": isin or None,
        "symbol": symbol or None,
        "quantity": number(quantity),
        "invested_value": number(invested_value),
        "collateral_quantity": number(collateral_quantity),
        "last_price": price(last_price),
        "close_price": price(close_price),
    }

class BrokerHoldingsSource:
    """
    Reads one broker's holdings from its REST API.

    Attributes:
        BROKER_NAME (str): The broker, as named in the `settings` collection and unified.broker_mappings.
        TIMEOUT_SECONDS (float): How long the broker may take to connect, and then to send each part of
            its answer, before the call is abandoned.
    """

    BROKER_NAME = None
    TIMEOUT_SECONDS = 5

    def fetch(self, client):
        """
        The broker's holdings response, as its API client's `data`.

        - `client` is the broker's API client, whose `get`/`post` carry the session.

        Raises `HoldingsUnavailable` when the broker answered without holdings, and lets the API client's
        own exceptions through. An account holding nothing is an empty answer, not an error.
        """
        raise NotImplementedError

    def normalize(self, data):
        """
        The holdings in what `fetch` returned, as a list of `holding` dicts.

        - `data` is the response `fetch` returned.
        """
        raise NotImplementedError

    def is_authentication_error(self, exception):
        """
        Whether an exception means the session is dead, so logging in again is the remedy.

        - `exception` is what `fetch` raised.
        """
        raise NotImplementedError
