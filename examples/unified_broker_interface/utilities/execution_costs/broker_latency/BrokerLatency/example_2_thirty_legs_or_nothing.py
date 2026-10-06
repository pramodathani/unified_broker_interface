"""Shows that a figure needs at least thirty legs behind it before it is trusted.

A broker that has handled only a handful of orders could show a large latency cost from one unlucky price jump. So a category's latency cost, and the broker's answer time, are left as None until thirty legs have been measured, and a broker with nothing measured is not written at all. This program fills in the legs by hand, so it reads no database.

Notice that the same legs give no figure at 29 and a figure at 30.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/broker_latency/BrokerLatency/example_2_thirty_legs_or_nothing.py
"""

import decimal

from unified_broker_interface.utilities.execution_costs.broker_latency import (
    BrokerLatency,
)


class ThirtyLegsOrNothingExample:
    """Builds a broker with 29 legs, then 30, and prints its figures each time.

    Attributes:
        broker (BrokerLatency): The broker's figures.
    """

    def __init__(self):
        """Builds a broker with no legs yet.

        Returns:
            None: This method returns nothing.
        """
        self.broker = BrokerLatency('dhan')

    def add_leg(self):
        """Adds one intraday leg that cost 1.5 basis points and was answered in 80 ms.

        Returns:
            None: This method returns nothing.
        """
        self.broker.latency_costs['intraday'].append(decimal.Decimal('1.5'))
        self.broker.answer_milliseconds.append(decimal.Decimal('80'))

    def run(self):
        """Adds 29 legs, prints, adds one more and prints again.

        Returns:
            None: This method returns nothing.
        """
        for index in range(29):
            self.add_leg()
        print(f"{self.broker.leg_count('intraday')} legs: cost {self.broker.latency_cost('intraday')}, answer {self.broker.typical_answer_milliseconds()}, write {self.broker.measured_anything()}")
        self.add_leg()
        print(f"{self.broker.leg_count('intraday')} legs: cost {self.broker.latency_cost('intraday')}, answer {self.broker.typical_answer_milliseconds()}, write {self.broker.measured_anything()}")


if __name__ == '__main__':
    ThirtyLegsOrNothingExample().run()
