"""Counts open positions for a condition that waits for a flat book, and asks a funds condition with no funds document.

`AccountCondition.open_position_count` counts the net positions whose quantity is not zero, and `figure` picks the reader for the field. With no funds document the figure is unknown and the condition does not hold. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/account_condition/AccountCondition/example_2_open_positions_and_no_document.py
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


class OpenPositionsAndNoDocumentExample:
    """Prints a flat-book condition and a missing document."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        flat = AccountCondition('open_positions', decimal.Decimal('0'), 'at_or_below')
        holding = StandInContext(None, {'net': [{'quantity': 75}, {'quantity': 0}, {'quantity': -10}]})
        print(f'Open positions: {flat.open_position_count(holding)}, flat: {flat.is_met(holding, {}, {}, 0.0, "BUY", "BUY")}')
        empty = StandInContext(None, {'net': [{'quantity': 0}]})
        print(f'After closing: {flat.figure(empty)}, flat: {flat.is_met(empty, {}, {}, 0.0, "BUY", "BUY")}')
        margin = AccountCondition('available_balance', decimal.Decimal('50000'), 'at_or_above')
        print(f'No funds document: figure {margin.figure(empty)}, holds {margin.is_met(empty, {}, {}, 0.0, "BUY", "BUY")}')


if __name__ == '__main__':
    OpenPositionsAndNoDocumentExample().run()
