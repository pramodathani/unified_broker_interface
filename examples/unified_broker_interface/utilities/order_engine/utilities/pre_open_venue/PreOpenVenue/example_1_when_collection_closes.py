"""Shows when the pre-open stops taking an order, for each kind of instrument and order type.

`PreOpenVenue.collection_closes` gives 09:10 for a cash limit order, 09:05 for a cash market order and 09:07 for a futures order, and refuses an option, which has no pre-open, and a stop order, which the pre-open does not take. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/pre_open_venue/PreOpenVenue/example_1_when_collection_closes.py
"""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.pre_open_venue import (
    PreOpenVenue,
)


class StandInInstrument:
    """Stands in for the instrument the placement reads.

    Attributes:
        exchange (str): The exchange, such as `nse`.
        bare_segment (str): The segment without its exchange.
        segment (str): The exchange-prefixed segment.
    """

    def __init__(self, exchange, bare_segment):
        """Builds the instrument.

        Args:
            exchange (str): The exchange.
            bare_segment (str): The segment without its exchange.

        Returns:
            None: This method returns nothing.
        """
        self.exchange = exchange
        self.bare_segment = bare_segment
        self.segment = f'{exchange}_{bare_segment}'


class StandInPlacement:
    """Stands in for the placement, answering one instrument.

    Attributes:
        instrument (StandInInstrument): The instrument.
    """

    def __init__(self, instrument):
        """Builds the placement.

        Args:
            instrument (StandInInstrument): The instrument.

        Returns:
            None: This method returns nothing.
        """
        self.instrument = instrument

    def market_context(self, instrument_id, with_quote, with_positions):
        """The instrument, as the placement answers it.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_positions (bool): Unused.

        Returns:
            tuple: The instrument and two unused values.
        """
        del instrument_id, with_quote, with_positions
        return self.instrument, None, None


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        body (dict): The order's settings.
        placement (StandInPlacement): The placement.
    """

    def __init__(self, exchange, bare_segment, order_type):
        """Builds the context.

        Args:
            exchange (str): The instrument's exchange.
            bare_segment (str): The instrument's segment without its exchange.
            order_type (str): The order type.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = f'{exchange}:{bare_segment}'
        self.body = {
            'order_type': order_type,
            'validity': 'DAY',
        }
        self.placement = StandInPlacement(StandInInstrument(exchange, bare_segment))

    def trading_segment(self):
        """The instrument's exchange-prefixed segment.

        Returns:
            str: The segment.
        """
        return self.placement.instrument.segment


class WhenCollectionClosesExample:
    """Asks one venue about six orders."""

    def run(self):
        """Prints when collection closes for each order, or why it is refused.

        Returns:
            None: This method returns nothing.
        """
        venue = PreOpenVenue('09:00:30')
        print('venue:', venue.described())
        orders = [
            ('nse', 'equities', 'LIMIT'),
            ('nse', 'equities', 'MARKET'),
            ('bse', 'exchange_traded_funds', 'LIMIT'),
            ('nse', 'equity_index_futures', 'LIMIT'),
            ('nse', 'equity_index_options', 'LIMIT'),
            ('nse', 'equities', 'SL'),
        ]
        for exchange, bare_segment, order_type in orders:
            context = StandInContext(exchange, bare_segment, order_type)
            try:
                closes = venue.collection_closes(context)
            except RefusedRequestError as error:
                print(f'{exchange}_{bare_segment} {order_type}: refused ({error})')
                continue
            print(f'{exchange}_{bare_segment} {order_type}: taken until {closes}')


if __name__ == '__main__':
    WhenCollectionClosesExample().run()
