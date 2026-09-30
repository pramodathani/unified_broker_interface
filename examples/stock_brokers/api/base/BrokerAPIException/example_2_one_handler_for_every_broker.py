"""Handles the errors of several brokers with one `except BrokerAPIException` clause.

Each broker module defines its own exception class, such as `DhanAPIException` or `ZerodhaAPIException`, and every one of them derives from `BrokerAPIException`. Code that works across brokers, such as a script that polls every broker's funds, can therefore catch the base class once and still read the broker's `code` and `message`, and use the exception's class to say which broker refused.

This program raises three brokers' exceptions with the codes and messages those brokers send for an expired token, catches them all with one handler, and prints what the handler sees. It needs no data store, no network and no broker.

Notice that every exception is caught by the same clause, and that each keeps its broker's own code: Dhan's `errorType`, Kite's `error_type` and Noren's `stat`.

Run it from the project root:

    python examples/stock_brokers/api/base/BrokerAPIException/example_2_one_handler_for_every_broker.py
"""

from stock_brokers.api.base import (
    BrokerAPIException,
)
from stock_brokers.api.dhan import (
    DhanAPIException,
)
from stock_brokers.api.flattrade import (
    FlattradeAPIException,
)
from stock_brokers.api.zerodha import (
    ZerodhaAPIException,
)


class RefusingBroker:
    """A stand-in for one broker's API object whose every request is refused with that broker's exception.

    Attributes:
        broker_name (str): The broker's name.
        refusal (BrokerAPIException): The exception every request raises.
    """

    def __init__(self, broker_name, refusal):
        """Holds the broker's name and the refusal.

        Args:
            broker_name (str): The broker's name.
            refusal (BrokerAPIException): The exception every request raises.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.refusal = refusal

    def get(self, url):
        """Refuses the request.

        Args:
            url (str): The URL requested.

        Returns:
            dict: Never returns.

        Raises:
            BrokerAPIException: Always, the broker's own subclass of it.
        """
        raise self.refusal


class OneHandlerExample:
    """Asks every broker for its funds and handles every refusal in one place.

    Attributes:
        brokers (list): The stand-in brokers to ask.
    """

    def __init__(self):
        """Builds the refusing brokers.

        Returns:
            None: This method returns nothing.
        """
        self.brokers = [
            RefusingBroker('dhan', DhanAPIException(code='Invalid_Authentication', message='Client ID or user generated access token is invalid or expired.')),
            RefusingBroker('zerodha', ZerodhaAPIException(code='TokenException', message='Incorrect `api_key` or `access_token`.')),
            RefusingBroker('flattrade', FlattradeAPIException(code='Not_Ok', message='Session Expired :  Invalid Session Key')),
        ]

    def run(self):
        """Sends one request to each broker and prints each refusal.

        Returns:
            None: This method returns nothing.
        """
        for broker in self.brokers:
            try:
                broker.get(url='/funds')
            except BrokerAPIException as error:
                print(f'{broker.broker_name}: {type(error).__name__} code={error.code} message={error.message}')


if __name__ == '__main__':
    OneHandlerExample().run()
