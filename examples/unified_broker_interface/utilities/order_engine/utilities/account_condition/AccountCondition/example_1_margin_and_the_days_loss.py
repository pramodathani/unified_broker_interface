"""Asks two account conditions as the free margin and the day's profit and loss change.

`AccountCondition.funds_figure` reads `available_balance` from the funds document's summary, or adds its realized and unrealized profit for `day_pnl`. `is_met` compares the figure with the level in the stated direction. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/account_condition/AccountCondition/example_1_margin_and_the_days_loss.py
"""

import decimal
import json

from unified_broker_interface.utilities.order_engine.utilities.account_condition import (
    AccountCondition,
)


class StandInCache:
    """Stands in for Redis, holding the combined funds document.

    Attributes:
        funds (dict | None): The funds document, or None when there is none.
    """

    def __init__(self, funds):
        """Builds the cache.

        Args:
            funds (dict | None): The funds document.

        Returns:
            None: This method returns nothing.
        """
        self.funds = funds

    def get(self, key):
        """One key, the funds document as JSON.

        Args:
            key (str): Unused, since only the funds document is held.

        Returns:
            str | None: The document, or None.
        """
        del key
        if self.funds is None:
            return None
        return json.dumps(self.funds)


class StandInPlacement:
    """Stands in for the placement: the cache and the combined positions.

    Attributes:
        cache (StandInCache): The cache.
        positions (dict): The combined positions document.
    """

    def __init__(self, funds, positions):
        """Builds the placement.

        Args:
            funds (dict | None): The funds document.
            positions (dict): The positions document.

        Returns:
            None: This method returns nothing.
        """
        self.cache = StandInCache(funds)
        self.positions = positions

    def market_context(self, instrument_id, with_quote, with_positions):
        """The positions, as the placement answers them.

        Args:
            instrument_id (str): Unused.
            with_quote (bool): Unused.
            with_positions (bool): Unused.

        Returns:
            tuple: Two unused values and the positions.
        """
        del instrument_id, with_quote, with_positions
        return None, None, self.positions


class StandInContext:
    """Stands in for the order's view of the plan order.

    Attributes:
        instrument_id (str): The order's instrument.
        placement (StandInPlacement): The placement.
    """

    def __init__(self, funds, positions):
        """Builds the context.

        Args:
            funds (dict | None): The funds document.
            positions (dict): The positions document.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_id = 'RELIANCE'
        self.placement = StandInPlacement(funds, positions)


class MarginAndTheDaysLossExample:
    """Asks two account conditions."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        margin = AccountCondition('available_balance', decimal.Decimal('50000'), 'at_or_above')
        loss = AccountCondition('day_pnl', decimal.Decimal('-5000'), 'at_or_below')
        margin.prepare(None, {})
        print(f'Reads quotes: {margin.needs_prices()}, watches: {margin.instruments()}')
        for available, realized, unrealized in ((40000.0, -1000.0, 0.0), (60000.0, -4000.0, -2500.0)):
            context = StandInContext({'summary': {'available_balance': available}, 'pnl': {'realized': realized, 'unrealized': unrealized}}, {})
            print(f'Free {available}, day {loss.funds_figure(context)}: margin freed {margin.is_met(context, {}, {}, 0.0, "BUY", "BUY")}, loss reached {loss.is_met(context, {}, {}, 0.0, "BUY", "BUY")}')
        print(f'As a dry run shows them: {margin.described()} and {loss.described()}')


if __name__ == '__main__':
    MarginAndTheDaysLossExample().run()
