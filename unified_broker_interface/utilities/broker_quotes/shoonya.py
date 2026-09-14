"""
Shoonya quotes, from `POST https://api.shoonya.com/NorenWClientAPI/GetQuotes`.

Shoonya is Finvasia's Noren deployment, so the request, the tick and the refusals are all
`NorenQuoteSource`'s; see `utilities/noren.py`. The API client sends the account's `ucc_code` as `uid`.
Shoonya allows about one request a second, which the service's one quote per request stays well within.
"""

from unified_broker_interface.utilities.broker_quotes.utilities.noren import NorenQuoteSource

class ShoonyaQuoteSource(NorenQuoteSource):
    """
    Fetches Shoonya quotes.
    """

    BROKER_NAME = "shoonya"
    QUOTE_URL = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"
