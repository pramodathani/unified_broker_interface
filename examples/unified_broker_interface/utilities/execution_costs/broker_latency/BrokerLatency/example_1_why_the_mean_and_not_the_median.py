"""Works out one broker's F&O latency cost from forty legs, most of which saw no price move at all.

While a broker handles an order, the mid-price usually does not move, so most legs have a latency cost of exactly zero, and the cost comes from the few that do move. That is why the figure is the mean over every leg: the median of these forty legs is zero, and a mean that dropped the highest and lowest few legs would be zero too. This program fills in the legs by hand, so it reads no database.

Notice that the median is 0 while the latency cost is 0.40 basis points, which is the cost an order pays on average.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/broker_latency/BrokerLatency/example_1_why_the_mean_and_not_the_median.py
"""

import decimal
import statistics

from unified_broker_interface.utilities.execution_costs.broker_latency import (
    BrokerLatency,
)

MOVES = [
    '4.20',
    '4.20',
    '8.40',
    '-4.20',
    '3.40',
]


class WhyTheMeanExample:
    """Fills in one broker's legs and prints its figures.

    Attributes:
        broker (BrokerLatency): The broker's figures.
    """

    def __init__(self):
        """Builds the broker with forty F&O legs and their answer times.

        Returns:
            None: This method returns nothing.
        """
        self.broker = BrokerLatency('zerodha')
        for index in range(40):
            latency_cost = decimal.Decimal('0')
            if index < len(MOVES):
                latency_cost = decimal.Decimal(MOVES[index])
            self.broker.latency_costs['fno'].append(latency_cost)
            self.broker.answer_milliseconds.append(decimal.Decimal(60 + index % 15))

    def run(self):
        """Prints the leg counts, the median, the latency cost and the answer time.

        Returns:
            None: This method returns nothing.
        """
        print(f"F&O legs: {self.broker.leg_count('fno')}, intraday legs: {self.broker.leg_count('intraday')}")
        print(f"Median of the F&O legs: {statistics.median(self.broker.latency_costs['fno'])}")
        print(f"F&O latency cost: {self.broker.latency_cost('fno')} bps")
        print(f"Intraday latency cost: {self.broker.latency_cost('intraday')}")
        print(f'Typical answer time: {self.broker.typical_answer_milliseconds()} ms')
        print(f'Anything to write: {self.broker.measured_anything()}')


if __name__ == '__main__':
    WhyTheMeanExample().run()
