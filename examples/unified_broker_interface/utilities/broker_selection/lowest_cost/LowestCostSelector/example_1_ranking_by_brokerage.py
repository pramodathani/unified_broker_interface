"""Ranks the same brokers for a delivery order, an intraday order and an options order, by what each broker charges.

A `LowestCostSelector` reads each broker's brokerage from the broker cost table and offers the order first to the broker that charges least for its category: `delivery` for a `CNC` order, `intraday` for any other equity order, and `fno` for a future or option. Among brokers that charge the same, it prefers the one that saves least on the other two categories, so a broker that is cheap for everything is kept for the orders only it is cheap for. A broker with no row in the table always comes last.

This program builds the cost table from rows in memory, taken from the table of 2026-09-29, so it needs no database. It queues the selector's Redis command on a stand-in pipeline that only records it, and answers it with every count at zero, as on a quiet morning, so no budget or pacing changes the ranking. The order and the instrument are small stand-ins carrying only the product and the kind of instrument the selector reads.

Notice that for the delivery order Flattrade, which charges nothing for anything, comes after the brokers that are free only for delivery orders, and Zerodha comes before Dhan only because it is earlier in the rotation. For the other two orders Groww comes before Zerodha and Dhan, which charge the same, because Groww saves nothing on other kinds of order. Stoxkart, which has no row, is last every time. The selector is built without a margin rate table, so its funds check is off and `passed_over_reason` rules no broker out.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/lowest_cost/LowestCostSelector/example_1_ranking_by_brokerage.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_selection.lowest_cost import (
    LowestCostSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)


class RecordingPipeline:
    """A stand-in for a Redis pipeline that records the script the selector queues.

    Attributes:
        evaluations (list): Each queued `eval`, as a tuple of key count and the keys and arguments.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.evaluations = []

    def eval(self, script, key_count, *keys_and_arguments):
        """Records one `eval`.

        Args:
            script (str): The Lua script.
            key_count (int): How many of the values are keys.
            *keys_and_arguments (str | int): The keys, then the arguments.

        Returns:
            RecordingPipeline: This pipeline.
        """
        del script
        self.evaluations.append((
            key_count,
            list(keys_and_arguments),
        ))
        return self


class StandInOrder:
    """A stand-in order carrying only the product the selector reads.

    Attributes:
        product (str): `CNC`, `MIS` or `NRML`.
    """

    def __init__(self, product):
        """Builds the order.

        Args:
            product (str): The product.

        Returns:
            None: This method returns nothing.
        """
        self.product = product


class StandInInstrument:
    """A stand-in instrument that only says what kind of instrument it is.

    Attributes:
        instrument_kind (str): `equity` or `derivative`.
    """

    def __init__(self, instrument_kind):
        """Builds the instrument.

        Args:
            instrument_kind (str): `equity` or `derivative`.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_kind = instrument_kind

    def kind(self):
        """The kind of instrument.

        Returns:
            str: `equity` or `derivative`.
        """
        return self.instrument_kind


class RankingByBrokerageExample:
    """Ranks six brokers for three different orders.

    Attributes:
        selector (LowestCostSelector): The selector being shown.
        rotation (list): The broker names not excluded by configuration, in turn order.
    """

    def __init__(self):
        """Builds the cost table from rows in memory and the selector over it.

        Returns:
            None: This method returns nothing.
        """
        rows = {
            'dhan': BrokerCosts('dhan', 9, 480, 7000, None, self.fees('0', '20', '20')),
            'flattrade': BrokerCosts('flattrade', 10, 180, None, None, self.fees('0', '0', '0')),
            'groww': BrokerCosts('groww', 9, 240, None, None, self.fees('20', '20', '20')),
            'shoonya': BrokerCosts('shoonya', 8, 540, None, None, self.fees('0', '5', '5')),
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, self.fees('0', '20', '20')),
        }
        cost_table = BrokerCostTable(logging.getLogger('example'), rows)
        self.selector = LowestCostSelector(cost_table)
        self.rotation = [
            'stoxkart',
            'zerodha',
            'groww',
            'shoonya',
            'flattrade',
            'dhan',
        ]

    @staticmethod
    def fees(delivery, fno, intraday):
        """Builds one broker's brokerage dictionary.

        Args:
            delivery (str): The brokerage for a delivery order.
            fno (str): The brokerage for a futures or options order.
            intraday (str): The brokerage for an intraday order.

        Returns:
            dict: The brokerage (decimal.Decimal) by category.
        """
        return {
            'delivery': decimal.Decimal(delivery),
            'fno': decimal.Decimal(fno),
            'intraday': decimal.Decimal(intraday),
        }

    def rank(self, label, order, instrument):
        """Ranks the rotation for one order and prints the ranking with each broker's fee and saving elsewhere.

        Args:
            label (str): What the order is, for the printout.
            order (StandInOrder): The order.
            instrument (StandInInstrument): The instrument.

        Returns:
            None: This method returns nothing.
        """
        pipeline = RecordingPipeline()
        commands_queued = self.selector.queue_redis_commands(pipeline, order, 'NSE:INFY')
        key_count = pipeline.evaluations[0][0]
        zero_counts = []
        for index in range(key_count):
            zero_counts.append(0)
        replies = [
            zero_counts,
        ]
        ranked = self.selector.ranked_brokers(order, instrument, self.rotation, replies)
        category = self.selector.category(order, instrument)
        highest = self.selector.highest_fees(self.rotation, self.selector.cost_table.rows)
        print(f'{label}: category {category}, {commands_queued} command queued reading {key_count} keys')
        for broker_name in ranked:
            costs = self.selector.cost_table.costs(broker_name)
            if costs is None:
                print(f'  {broker_name}: no row in the cost table')
                continue
            saving = self.selector.versatility(costs, category, highest)
            print(f'  {broker_name}: fee {costs.fee(category)}, saves {saving} on other categories')

    def run(self):
        """Ranks the rotation for a delivery, an intraday and an options order.

        Returns:
            None: This method returns nothing.
        """
        print(f'Selector: {LowestCostSelector.NAME}')
        print(f'Rotation: {self.rotation}')
        self.rank('Delivery order in INFY', StandInOrder('CNC'), StandInInstrument('equity'))
        self.rank('Intraday order in INFY', StandInOrder('MIS'), StandInInstrument('equity'))
        self.rank('NIFTY option', StandInOrder('NRML'), StandInInstrument('derivative'))
        print(f'Reason to pass over zerodha for funds: {self.selector.passed_over_reason("zerodha")}')


if __name__ == '__main__':
    RankingByBrokerageExample().run()
