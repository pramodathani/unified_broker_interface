"""
Flattrade quotes, from `POST https://piconnect.flattrade.in/PiConnectAPI/GetQuotes`.

Flattrade runs on Noren, so the request, the tick and the refusals are all `NorenQuoteSource`'s; see
`utilities/noren.py`. The API client sends the account's `username` as `uid`.
"""

from unified_broker_interface.utilities.broker_quotes.utilities.noren import NorenQuoteSource

class FlattradeQuoteSource(NorenQuoteSource):
    """
    Fetches Flattrade quotes.
    """

    BROKER_NAME = "flattrade"
    QUOTE_URL = "https://piconnect.flattrade.in/PiConnectAPI/GetQuotes"
