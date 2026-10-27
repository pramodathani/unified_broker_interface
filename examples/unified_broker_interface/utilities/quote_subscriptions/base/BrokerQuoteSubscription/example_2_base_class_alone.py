"""Shows what the base class does on its own: it keeps the Redis client and refuses to spell anything.

`BrokerQuoteSubscription` holds what every broker's spelling shares, which is only the Redis client a spelling may need, kept as `cache`. Its `member` raises `NotImplementedError`, so a broker that forgets to implement it fails loudly rather than streaming nothing. The program passes a plain string in place of a Redis client, because the base class only stores it.

It needs no data store, no network and no broker login.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/base/BrokerQuoteSubscription/example_2_base_class_alone.py
"""

from unified_broker_interface.utilities.quote_subscriptions.base import (
    BrokerQuoteSubscription,
)


class BaseClassAloneExample:
    """Builds the base class directly and asks it for a member.

    Attributes:
        spelling (BrokerQuoteSubscription): The base class instance.
    """

    def __init__(self):
        """Builds the base class with a stand-in Redis client.

        Returns:
            None: This method returns nothing.
        """
        self.spelling = BrokerQuoteSubscription('stand-in Redis client')

    def run(self):
        """Prints the stored client, the broker name and what `member` raises.

        Returns:
            None: This method returns nothing.
        """
        print(f'Broker name: {BrokerQuoteSubscription.BROKER_NAME}')
        print(f'Cache kept: {self.spelling.cache}')
        identity = {
            'exchange': 'nse',
            'segment': 'nse_equities',
            'shape': 'security',
        }
        try:
            self.spelling.member(identity, '2885', None)
        except NotImplementedError:
            print('member raised NotImplementedError')


if __name__ == '__main__':
    BaseClassAloneExample().run()
