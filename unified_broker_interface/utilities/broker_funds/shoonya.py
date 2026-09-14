"""
Shoonya funds, from `POST https://api.shoonya.com/NorenWClientAPI/Limits`.

Shoonya is Finvasia's Noren deployment, so the request, the record and the refusals are all
`NorenFundsSource`'s; see `utilities/noren.py`. The account is the `ucc_code` in Shoonya's settings.
"""

from unified_broker_interface.utilities.broker_funds.utilities.noren import NorenFundsSource

class ShoonyaFundsSource(NorenFundsSource):
    """
    Reads Shoonya funds.
    """

    BROKER_NAME = "shoonya"
    LIMITS_URL = "https://api.shoonya.com/NorenWClientAPI/Limits"
    ACCOUNT_FIELD = "ucc_code"
