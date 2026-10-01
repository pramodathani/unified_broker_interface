"""Sizes a delta hedge in Nifty futures for a bought call as it fills, at a volatility of 12.5%.

`FillDelta.delta` is the call's Black-76 delta with the future's last price, 26,000, as the forward and the strike at 25,000. `scaled` is the size of the delta times what filled, rounded to the future's lot of 75. The option expires years away, so its delta barely moves from one day to the next, and it is printed to two places. `is_call` is what the `against_delta` side reads to sell the future against a call and buy it against a put. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/fill_delta/FillDelta/example_1_hedging_a_bought_call.py
"""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.fill_delta import (
    FillDelta,
)


class StandInInstrument:
    """Stands in for an instrument in the catalogue.

    Attributes:
        identity (dict): Its option type, strike and expiry, empty for a stock or a future.
        handles (dict): Each broker's handle, with its lot size.
    """

    def __init__(self, identity, handles):
        """Builds the instrument.

        Args:
            identity (dict): Its option details.
            handles (dict): Each broker's handle.

        Returns:
            None: This method returns nothing.
        """
        self.identity = identity
        self.handles = handles


class StandInPlacement:
    """Stands in for the placement: a catalogue of two instruments and the future's quote.

    Attributes:
        instruments (dict): Each instrument, by id.
        future_price (float | None): The future's last price, or None when it has none.
    """

    def __init__(self, option_identity, future_price):
        """Builds the placement.

        Args:
            option_identity (dict): The plan's instrument's option details.
            future_price (float | None): The future's last price.

        Returns:
            None: This method returns nothing.
        """
        self.instruments = {
            'OPTION': StandInInstrument(option_identity, {}),
            'NIFTY FUTURE': StandInInstrument(
                {},
                {
                    'zerodha': {
                        'lot_size': 75,
                    },
                },
            ),
        }
        self.future_price = future_price

    def market_context(self, instrument_id, with_quote, with_depth):
        """An instrument, and the future's quote when asked.

        Args:
            instrument_id (str): The instrument.
            with_quote (bool): Whether to read its quote.
            with_depth (bool): Unused.

        Returns:
            tuple: The instrument, its quote or None, and an unused value.
        """
        del with_depth
        quote = None
        if with_quote and self.future_price is not None:
            quote = {
                'last_price': self.future_price,
            }
        return self.instruments[instrument_id], quote, None


class StandInParent:
    """Stands in for the plan's parent record.

    Attributes:
        parent_order_id (str): The parent's id.
        instrument_id (str): The plan's own instrument, the option.
    """

    def __init__(self):
        """Builds the parent.

        Returns:
            None: This method returns nothing.
        """
        self.parent_order_id = 'plan-1'
        self.instrument_id = 'OPTION'


class PrintingLogger:
    """A logger that prints each warning, so it is part of the output."""

    def warning(self, message):
        """Prints a warning.

        Args:
            message (str): The message.

        Returns:
            None: This method returns nothing.
        """
        print(f'WARNING {message}')


class StandInPlanOrder:
    """Stands in for the plan order, which holds the logger.

    Attributes:
        logger (PrintingLogger): The logger.
    """

    def __init__(self):
        """Builds the plan order.

        Returns:
            None: This method returns nothing.
        """
        self.logger = PrintingLogger()


class StandInContext:
    """Stands in for the hedge order's view of the plan order.

    Attributes:
        instrument_id (str): The hedge instrument.
        parent (StandInParent): The plan's parent.
        plan_order (StandInPlanOrder): The plan order.
        placement (StandInPlacement): The placement.
    """

    def __init__(self, option_identity, future_price):
        """Builds the context.

        Args:
            option_identity (dict): The plan's instrument's option details.
            future_price (float | None): The future's last price.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'NIFTY FUTURE'
        self.parent = StandInParent()
        self.plan_order = StandInPlanOrder()
        self.placement = StandInPlacement(option_identity, future_price)

    def tick_size(self, instrument_id=None):
        """The hedge's tick size.

        Args:
            instrument_id (str | None): Unused.

        Returns:
            decimal.Decimal: 0.05.
        """
        del instrument_id
        return decimal.Decimal('0.05')

    def chosen_broker(self):
        """The broker the plan's orders went to.

        Returns:
            str: Zerodha.
        """
        return 'zerodha'


class HedgingABoughtCallExample:
    """Sizes the hedge of a call and a put."""

    def option(self, option_type):
        """An option's details, struck at 25,000 and expiring years away.

        Args:
            option_type (str): CE or PE.

        Returns:
            dict: The details.
        """
        return {
            'option_type': option_type,
            'strike_price': 25000.0,
            'expiry_date': '2031-12-30',
        }

    def run(self):
        """Prints the delta and the hedge for a few fills.

        Returns:
            None: This method returns nothing.
        """
        sizing = FillDelta(decimal.Decimal('12.5'), True)
        call = StandInContext(self.option('CE'), 26000.0)
        print(f'check: {sizing.check(call)}')
        print(f'is a call: {sizing.is_call(call)}')
        strike, _, _ = sizing.option_details(call)
        print(f'strike: {strike}')
        print(f'delta: {sizing.delta(call):.2f}')
        fills = (
            75,
            750,
            1500,
        )
        for filled in fills:
            print(f'{filled} filled: hedge {sizing.scaled(call, filled)}')
        put = StandInContext(self.option('PE'), 26000.0)
        print(f'the put is a call: {sizing.is_call(put)}, delta {sizing.delta(put):.2f}, 1500 filled: hedge {sizing.scaled(put, 1500)}')
        print(f'As a dry run shows it: {sizing.described()}')


if __name__ == '__main__':
    HedgingABoughtCallExample().run()
