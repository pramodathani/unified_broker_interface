"""How Flattrade's PiConnect API, a Noren platform, takes and cancels orders."""

from unified_broker_interface.utilities.broker_orders.noren import NorenOrders


class FlattradeOrders(NorenOrders):
    """Flattrade's order requests, which differ from Shoonya's only in the base URL and the account settings field."""

    BROKER_NAME = 'flattrade'
    BASE_URL = 'https://piconnect.flattrade.in/PiConnectAPI'
    ACCOUNT_SETTINGS_FIELD = 'username'
    PLACE_SETTINGS_FIELDS = [
        'username',
    ]
    CANCEL_SETTINGS_FIELDS = [
        'username',
    ]
