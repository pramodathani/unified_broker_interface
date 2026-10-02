"""Shows which segments a volume-weighted order weights by the equity day's volume shape, and which get even slices instead.

The default volume profile describes an ordinary NSE equity day, heavy at the open and the close and quiet across lunch. It says nothing about a commodity that moves when a foreign market opens, so a currency or commodity order with no `volume_profile` of its own is sliced evenly. `is_equity` is what decides it. An instrument with no segment at all is taken as equity, which keeps what volume-weighted orders did before they read the segment. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/session_open/SessionOpen/example_2_which_days_have_an_equity_shape.py
"""

from unified_broker_interface.utilities.order_engine.utilities.session_open import (
    SessionOpen,
)


class WhichDaysHaveAnEquityShapeExample:
    """Prints whether each segment takes the equity volume shape.

    Attributes:
        segments (list): The segments shown, the empty string standing for an instrument with none.
    """

    def __init__(self):
        """Lists the segments.

        Returns:
            None: This method returns nothing.
        """
        self.segments = [
            'nse_equities',
            'bse_equities',
            'nse_currency_futures',
            'mcx_commodity_options',
            '',
        ]

    def run(self):
        """Prints one line per segment, with what a VWAP with no profile of its own does there.

        Returns:
            None: This method returns nothing.
        """
        for segment in self.segments:
            session = SessionOpen(segment)
            if session.is_equity():
                slicing = 'the equity volume shape'
            else:
                slicing = 'even slices'
            shown = segment or '(no segment)'
            print(f'{shown:<24} equity {str(session.is_equity()):<5} -> a VWAP with no profile uses {slicing}, half hours from {session.opens_at()}')


if __name__ == '__main__':
    WhichDaysHaveAnEquityShapeExample().run()
