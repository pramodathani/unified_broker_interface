"""Shows how order-rate budgets, recent choices and the pacing of a daily budget change the ranking for an intraday order.

Being cheap is not enough: a `LowestCostSelector` puts a broker last when its per-minute, per-hour or per-day budget is used up, and among equally cheap brokers it prefers the one whose fullest window is least full. It learns the counts from one Lua script queued on the route's Redis pipeline, and it also remembers the brokers it chose itself in the last second, minute and hour, because the counts in Redis only rise once an order is actually sent.

This program builds the cost table from rows in memory, so it needs no database, and answers the selector's Redis script with scripted counts instead of reading Redis. Shoonya has used its whole per-minute budget, Dhan half of its own, and Fyers a fifth. It then records three choices of Kotak in this process, and prints what the selector makes of each broker. Finally it asks how a per-day budget is paced through the session, using fixed moments and fixed counts so the output never depends on the time it runs.

Notice that Shoonya, the cheapest broker, is ranked last because it is blocked; that Kotak leads the 20-rupee brokers because it is no cheaper for other kinds of order, and the other three follow in order of pressure; that Kotak's counts come from this process's own choices, because Redis has not seen them yet; and that 2,000 orders out of a 4,500 daily budget is too many at 10:00 but comfortable by 15:00.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_selection/lowest_cost/LowestCostSelector/example_2_budgets_and_pacing.py
"""

import datetime
import decimal
import logging

from unified_broker_interface.utilities.broker_selection.lowest_cost import (
    LowestCostSelector,
)
from unified_broker_interface.utilities.broker_selection.utilities.broker_cost_table import (
    BrokerCosts,
    BrokerCostTable,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_store import (
    INDIA,
)


class RecordingPipeline:
    """A stand-in for a Redis pipeline that records the script the selector queues.

    Attributes:
        key_counts (list): The number of keys of each queued `eval`.
    """

    def __init__(self):
        """Builds an empty pipeline.

        Returns:
            None: This method returns nothing.
        """
        self.key_counts = []

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
        del keys_and_arguments
        self.key_counts.append(key_count)
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
    """A stand-in equity instrument.

    Attributes:
        instrument_kind (str): `equity` or `derivative`.
    """

    def __init__(self):
        """Builds the instrument.

        Returns:
            None: This method returns nothing.
        """
        self.instrument_kind = 'equity'

    def kind(self):
        """The kind of instrument.

        Returns:
            str: `equity`.
        """
        return self.instrument_kind


class BudgetsAndPacingExample:
    """Ranks five brokers for an intraday order under scripted counts, then shows daily pacing.

    Attributes:
        selector (LowestCostSelector): The selector being shown.
        rotation (list): The broker names not excluded by configuration, in turn order.
        scripted_counts (dict): Each broker's counts in the last second, minute and hour and today, as the Redis script would return them.
    """

    def __init__(self):
        """Builds the cost table from rows in memory, the selector over it and the scripted counts.

        Returns:
            None: This method returns nothing.
        """
        rows = {
            'dhan': BrokerCosts('dhan', 9, 480, 7000, None, self.fees('0', '20', '20')),
            'fyers': BrokerCosts('fyers', 8, 180, None, 100000, self.fees('0', '20', '20')),
            'kotak': BrokerCosts('kotak', 9, 600, None, None, self.fees('20', '20', '20')),
            'shoonya': BrokerCosts('shoonya', 8, 540, None, None, self.fees('0', '5', '5')),
            'zerodha': BrokerCosts('zerodha', 9, 375, None, 4500, self.fees('0', '20', '20')),
        }
        cost_table = BrokerCostTable(logging.getLogger('example'), rows)
        self.selector = LowestCostSelector(cost_table)
        self.rotation = [
            'dhan',
            'fyers',
            'kotak',
            'shoonya',
            'zerodha',
        ]
        self.scripted_counts = {
            'dhan': [
                0,
                240,
                900,
                0,
            ],
            'fyers': [
                0,
                36,
                400,
                0,
            ],
            'kotak': [
                0,
                0,
                0,
                0,
            ],
            'shoonya': [
                0,
                540,
                2000,
                0,
            ],
            'zerodha': [
                0,
                0,
                0,
                0,
            ],
        }

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

    def script_reply(self):
        """Builds the Redis script's reply: four counts per broker, brokers in name order.

        Returns:
            list: The counts (int), flattened.
        """
        reply = []
        for broker_name in sorted(self.selector.cost_table.rows):
            for count in self.scripted_counts[broker_name]:
                reply.append(count)
        return reply

    def show_ranking(self):
        """Ranks the rotation for an intraday order and prints each broker's counts, block and pressure.

        Returns:
            None: This method returns nothing.
        """
        order = StandInOrder('MIS')
        instrument = StandInInstrument()
        pipeline = RecordingPipeline()
        self.selector.queue_redis_commands(pipeline, order, 'NSE:INFY')
        replies = [
            self.script_reply(),
        ]
        names = sorted(self.selector.cost_table.rows)
        stored = self.selector.stored_counts(names, replies)
        print(f'Script reads {pipeline.key_counts[0]} keys; Kotak in Redis: {stored["kotak"]}')
        print(f'Kotak chosen by this process: {self.selector.chosen_counts("kotak")}')
        ranked = self.selector.ranked_brokers(order, instrument, self.rotation, replies)
        print(f'Ranked for an intraday order: {ranked}')
        for broker_name in ranked:
            costs = self.selector.cost_table.costs(broker_name)
            used = self.selector.used_counts(broker_name, stored)
            blocked = self.selector.is_blocked(costs, used)
            pressure = self.selector.pressure(costs, used, 0.5)
            print(f'  {broker_name}: fee {costs.fee("intraday")}, minute {used["minute"]}, blocked {blocked}, pressure {pressure:.3f}')

    def show_pacing(self):
        """Prints how full a 4,500-order daily budget looks with 2,000 orders used at three times of day.

        Returns:
            None: This method returns nothing.
        """
        zerodha = self.selector.cost_table.costs('zerodha')
        used = {
            'second': 0,
            'minute': 0,
            'hour': 0,
            'day': 2000,
        }
        times = [
            datetime.time(9, 0),
            datetime.time(10, 0),
            datetime.time(15, 0),
        ]
        for time_of_day in times:
            moment = datetime.datetime.combine(datetime.date(2026, 9, 30), time_of_day, tzinfo=INDIA)
            fraction = self.selector.day_fraction(moment)
            pressure = self.selector.pressure(zerodha, used, fraction)
            print(f'At {time_of_day}: {fraction:.3f} of the session passed, Zerodha pressure {pressure:.3f}')
        used['day'] = 4300
        print(f'Zerodha blocked at 4300 of 4500 today: {self.selector.is_blocked(zerodha, used)}')

    def run(self):
        """Records three choices of Kotak, ranks the rotation, then shows daily pacing.

        Returns:
            None: This method returns nothing.
        """
        for choice in range(3):
            self.selector.record_chosen('kotak')
        self.show_ranking()
        self.show_pacing()


if __name__ == '__main__':
    BudgetsAndPacingExample().run()
