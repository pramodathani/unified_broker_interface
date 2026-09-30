"""Shows what the base class itself does, and lists what every real broker quote source sets on top of it.

`BrokerQuoteSource` is the contract the quote service relies on. On its own it has no broker, and both of its methods raise `NotImplementedError`, so a broker module that forgot one of them fails loudly the first time it is used rather than returning something wrong. This program calls both methods on the bare base class and catches that error.

It then builds one instance of every broker quote source in the project and prints its broker name, its timeout and whether it answers the two questions itself. Building a source sends nothing: a source only talks to its broker inside `fetch`, through the API client it is handed, so no network, data store or login is needed.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_quotes/base/BrokerQuoteSource/example_2_what_every_broker_provides.py
"""

from unified_broker_interface.utilities.broker_quotes.base import (
    BrokerQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.dhan import (
    DhanQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.flattrade import (
    FlattradeQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.fyers import (
    FyersQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.groww import (
    GrowwQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.indmoney import (
    IndmoneyQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.kotak import (
    KotakQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.shoonya import (
    ShoonyaQuoteSource,
)
from unified_broker_interface.utilities.broker_quotes.zerodha import (
    ZerodhaQuoteSource,
)


class WhatEveryBrokerProvidesExample:
    """Calls the bare base class's methods, then lists every broker's source.

    Attributes:
        sources (list): One instance of every broker quote source.
    """

    def __init__(self):
        """Builds one instance of every broker quote source.

        Returns:
            None: This method returns nothing.
        """
        self.sources = [
            ZerodhaQuoteSource(),
            DhanQuoteSource(),
            KotakQuoteSource(),
            FlattradeQuoteSource(),
            ShoonyaQuoteSource(),
            IndmoneyQuoteSource(),
            FyersQuoteSource(),
            GrowwQuoteSource(),
        ]

    def run(self):
        """Prints what the base class does and what each broker's source sets.

        Returns:
            None: This method returns nothing.
        """
        bare = BrokerQuoteSource()
        print(f'Base class: broker {bare.BROKER_NAME}, timeout {bare.TIMEOUT_SECONDS} seconds')
        try:
            bare.fetch(None, {}, {}, 0.0)
        except NotImplementedError:
            print('BrokerQuoteSource.fetch raises NotImplementedError')
        try:
            bare.is_authentication_error(RuntimeError('refused'))
        except NotImplementedError:
            print('BrokerQuoteSource.is_authentication_error raises NotImplementedError')
        for source in self.sources:
            source_class = type(source)
            own_fetch = source_class.fetch is not BrokerQuoteSource.fetch
            own_check = source_class.is_authentication_error is not BrokerQuoteSource.is_authentication_error
            print(f'{source_class.__name__}: broker {source.BROKER_NAME}, timeout {source.TIMEOUT_SECONDS} seconds, fetch implemented {own_fetch}, authentication check implemented {own_check}')


if __name__ == '__main__':
    WhatEveryBrokerProvidesExample().run()
