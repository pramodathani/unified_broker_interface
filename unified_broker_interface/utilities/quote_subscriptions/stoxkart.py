"""Stoxkart's quote subscriptions: `EXCHANGE:TOKEN`, with the exchange read from Stoxkart's own instrument master."""

import json

from stock_brokers.instruments.mapping.utilities.segments import (
    CASH_SEGMENTS,
    INDEX_SEGMENTS,
    split_segment_value,
)
from stock_brokers.websockets.stoxkart import SEGMENTS
from unified_broker_interface.utilities.quote_subscriptions.base import BrokerQuoteSubscription

MASTER_KEY = "stoxkart:instruments:master"
MASTER_META_KEY = "stoxkart:instruments:meta"


class StoxkartQuoteSubscription(BrokerQuoteSubscription):
    """Spells a Stoxkart mapping row as `EXCHANGE:TOKEN`, such as `NFO:35000`.

    About 20,900 of Stoxkart's tokens appear under more than one of its exchanges, so the token alone does not say which exchange to subscribe it on. The canonical exchange narrows the choice to Stoxkart's exchanges for it, and the master says which of those list the token; where both a cash and a currency exchange remain, the segment decides. The broadcast feed streams only the exchanges in `SEGMENTS`, so an instrument on any other is answered None.

    Attributes:
        EXCHANGES (dict): Each canonical exchange to Stoxkart's exchanges for its cash and indices, currency derivatives and other derivatives.
    """

    BROKER_NAME = "stoxkart"
    EXCHANGES = {
        "nse": {
            "cash": "NSE",
            "currency": "NSECD",
            "derivative": "NFO",
        },
        "bse": {
            "cash": "BSE",
            "currency": "BSECD",
            "derivative": "BFO",
        },
        "mcx": {
            "cash": "MCX",
            "currency": "MCX",
            "derivative": "MCX",
        },
        "ncdex": {
            "cash": "NCDEX",
            "currency": "NCDEX",
            "derivative": "NCDEX",
        },
    }

    def __init__(self, cache):
        """Keeps the Redis client; the master is read on the first call to `member`.

        Args:
            cache (redis.Redis): The Redis client holding `stoxkart:instruments:master`.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(cache)
        self._exchanges_by_token = None

    def member(self, identity, broker_token, order_symbol):
        """Stoxkart's exchange for the token and the token.

        Args:
            identity (dict): The unified instrument's row.
            broker_token (str): Stoxkart's token.
            order_symbol (str | None): Unused.

        Returns:
            str | None: The member, or None when the master does not list the token on a matching exchange or the broadcast feed does not stream that exchange.
        """
        del order_symbol
        if self._exchanges_by_token is None:
            self._exchanges_by_token = self._read_master()
        exchange, bare = split_segment_value(identity["segment"])
        names = self.EXCHANGES.get(exchange)
        if names is None:
            return None
        listed = self._exchanges_by_token.get(str(broker_token), set())
        candidates = []
        for name in (names["cash"], names["currency"], names["derivative"]):
            if name in listed and name not in candidates:
                candidates.append(name)
        if not candidates:
            return None
        chosen = candidates[0]
        if len(candidates) > 1:
            if bare.startswith("currenc"):
                wanted = names["currency"]
            elif bare in CASH_SEGMENTS or bare in INDEX_SEGMENTS:
                wanted = names["cash"]
            else:
                wanted = names["derivative"]
            if wanted in candidates:
                chosen = wanted
            elif wanted == names["derivative"] and names["cash"] in candidates:
                chosen = names["cash"]
        if chosen not in SEGMENTS:
            return None
        return f"{chosen}:{broker_token}"

    def _read_master(self):
        """Reads which of Stoxkart's exchanges list each token.

        Returns:
            dict[str, set[str]]: Each token to the exchanges whose master rows carry it.
        """
        meta = json.loads(self.cache.get(MASTER_META_KEY) or "{}")
        columns = meta.get("columns") or []
        token_position = columns.index("token")
        exchanges_by_token = {}
        for key, value in self.cache.hscan_iter(MASTER_KEY, count=10000):
            row = json.loads(value)
            exchange = key.split(":")[0]
            token = str(row[token_position])
            exchanges_by_token.setdefault(token, set()).add(exchange)
        return exchanges_by_token
