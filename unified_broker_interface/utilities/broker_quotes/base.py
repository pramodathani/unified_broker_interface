"""
What a broker's REST quote module provides.

A module fetches one instrument's quote and returns it as a tick in the market feeds' contract - the
twenty keys every broker's quote feed in `bin/<broker>/quotes` writes - with
`instrument_token` spelled the way that broker's feed spells it. That is what lets the broker's
`TickNormalizer` and the `TickResolver` handle a fetched quote exactly like a streamed one, so a quote
from either path means the same thing.
"""

class QuoteUnavailable(Exception):
    """
    The broker answered, but not with a usable quote for the instrument.
    """

def contract_tick(broker, instrument_token, exchange, received_at):
    """
    A contract tick with every key present and nothing filled in but its identity and receipt time.

    - `broker` is the broker name.
    - `instrument_token` is the token as the broker's market feed spells it on ticks.
    - `exchange` is the canonical exchange.
    - `received_at` is when the quote was fetched, in epoch seconds.
    """
    return {
        "id": str(instrument_token),
        "broker": broker,
        "instrument_token": instrument_token,
        "exchange": exchange,
        "mode": "full",
        "last_price": None,
        "last_quantity": None,
        "average_price": None,
        "volume": None,
        "buy_quantity": None,
        "sell_quantity": None,
        "ohlc": {"open": None, "high": None, "low": None, "close": None},
        "change": None,
        "oi": None,
        "oi_day_high": None,
        "oi_day_low": None,
        "last_trade_time": None,
        "exchange_timestamp": None,
        "depth": {"buy": [], "sell": []},
        "received_at": received_at,
    }

class BrokerQuoteSource:
    """
    Fetches quotes from one broker's REST API as contract ticks.

    Attributes:
        BROKER_NAME (str): The broker, as named in unified.broker_mappings.
        TIMEOUT_SECONDS (float): How long one quote request may take before the next broker is tried.
    """

    BROKER_NAME = None
    TIMEOUT_SECONDS = 5

    def fetch(self, client, handle, identity, received_at):
        """
        One instrument's quote as a contract tick.

        - `client` is the broker's API client, whose `get`/`post` carry the session.
        - `handle` is the broker's order handle for the instrument: `broker_token`, `order_symbol`,
          `lot_size` and `tick_size`.
        - `identity` is the instrument's identity.
        - `received_at` is the instant to stamp on the tick, in epoch seconds.

        Raises `QuoteUnavailable` when the broker has no quote for it, and lets the API client's own
        exceptions through.
        """
        raise NotImplementedError

    def is_authentication_error(self, exception):
        """
        Whether an exception means the session is dead, so logging in again is the remedy.

        - `exception` is what `fetch` raised.
        """
        raise NotImplementedError
