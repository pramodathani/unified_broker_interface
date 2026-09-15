"""How Shoonya's Noren API takes, modifies and cancels orders."""

from unified_broker_interface.utilities.broker_orders.noren import NorenOrders


class ShoonyaOrders(NorenOrders):
    """Shoonya's order requests, which differ from Flattrade's only in the base URL and the account settings field."""

    BROKER_NAME = 'shoonya'
    BASE_URL = 'https://api.shoonya.com/NorenWClientAPI'
    ACCOUNT_SETTINGS_FIELD = 'ucc_code'
    MAXIMUM_IDLE_SECONDS = 45.0
    WARM_URL = 'https://api.shoonya.com/'
    WARM_INTERVAL_SECONDS = 15.0
    PLACE_SETTINGS_FIELDS = [
        'ucc_code',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'ucc_code',
    ]
    MODIFY_SETTINGS_FIELDS = [
        'ucc_code',
    ]
