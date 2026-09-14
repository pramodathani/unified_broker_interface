"""
Flattrade funds, from `POST https://piconnect.flattrade.in/PiConnectAPI/Limits`.

Flattrade runs on Noren, so the request, the record and the refusals are all `NorenFundsSource`'s; see
`utilities/noren.py`. The account is the `username` in Flattrade's settings.
"""

from unified_broker_interface.utilities.broker_funds.utilities.noren import NorenFundsSource

class FlattradeFundsSource(NorenFundsSource):
    """
    Reads Flattrade funds.
    """

    BROKER_NAME = "flattrade"
    LIMITS_URL = "https://piconnect.flattrade.in/PiConnectAPI/Limits"
    ACCOUNT_FIELD = "username"
