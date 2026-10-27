"""Shows what one broker's quote capacity holds, and how its total room is worked out.

A `QuoteCapacity` is one row of `unified.broker_quote_capacities`: how many quote sockets a broker may open, how many instruments each carries, and its preference when an instrument has several carriers. Its `total` is sockets times instruments per socket, which is how many instruments the allocation may give the broker. The rows below are the ones measured on 2026-10-27 for Zerodha and Dhan, and a broker left out with 0 sockets.

It needs no data store, no network and no broker login.

Notice that the broker with 0 sockets has a total of 0, which is how the allocation leaves a broker out.

Run it from the project root:

    python examples/unified_broker_interface/utilities/quote_subscriptions/utilities/allocation/QuoteCapacity/example_1_total_room.py
"""

from unified_broker_interface.utilities.quote_subscriptions.utilities.allocation import (
    QuoteCapacity,
)


class TotalRoomExample:
    """Builds three capacities and prints their figures.

    Attributes:
        capacities (list[QuoteCapacity]): The capacities being shown.
    """

    def __init__(self):
        """Builds the capacities.

        Returns:
            None: This method returns nothing.
        """
        self.capacities = [
            QuoteCapacity('zerodha', 24, 4000, 1),
            QuoteCapacity('dhan', 10, 5000, 3),
            QuoteCapacity('groww', 0, 0, 100),
        ]

    def run(self):
        """Prints each capacity's sockets, instruments per socket, preference and total.

        Returns:
            None: This method returns nothing.
        """
        for capacity in self.capacities:
            print(f'{capacity.broker}: {capacity.sockets} sockets x {capacity.instruments_per_socket} = {capacity.total}, preference {capacity.preference}')


if __name__ == '__main__':
    TotalRoomExample().run()
