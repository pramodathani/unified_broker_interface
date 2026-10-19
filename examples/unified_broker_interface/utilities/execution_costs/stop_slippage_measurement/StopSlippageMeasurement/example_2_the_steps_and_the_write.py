"""Walks through the measurement's steps one at a time, then writes the result and shows what was sent to the database.

`measure` reads the events, folds them into parents with `parents_from`, keeps the fired protective stops with `fired_stops`, reads their segments and finds each close with `find_close`. This program calls those steps itself on a stand-in database, so it needs no PostgreSQL, and then calls `write`, which creates the table if it is missing, deletes the day's rows and inserts the new ones.

Notice that an entry plan whose trigger fired is not a protective stop, so `protective_trigger` gives it None and it is not measured.

Run it from the project root:

    python examples/unified_broker_interface/utilities/execution_costs/stop_slippage_measurement/StopSlippageMeasurement/example_2_the_steps_and_the_write.py
"""

import datetime
import logging

from test_runs.stop_slippage_stand_ins import StandInStopDatabase
from unified_broker_interface.utilities.execution_costs.stop_slippage_measurement import (
    EVENT_COLUMNS,
    StopSlippageMeasurement,
)

INDIA = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPTION = '065e67b5-b3f8-5374-a0bb-4ddc7786338d'


class StepsAndWriteExample:
    """Runs each step and the write.

    Attributes:
        database (StandInStopDatabase): The scripted events.
        measurement (StopSlippageMeasurement): The measurement.
    """

    def __init__(self):
        """Scripts two stops and an entry plan, and builds the measurement.

        Returns:
            None: This method returns nothing.
        """
        self.database = StandInStopDatabase()
        self.database.segments[OPTION] = 'nse_equity_index_options'
        self.database.add_stop(datetime.datetime(2026, 10, 19, 14, 30, tzinfo=INDIA), 'later-stop', OPTION, '190.00', fill_price='189.80')
        self.database.add_stop(datetime.datetime(2026, 10, 19, 14, 10, tzinfo=INDIA), 'earlier-stop', OPTION, '185.00', fill_price='184.50')
        entry = {'parameters': {'plan': {'order': {'side': 'entry', 'trigger': {'price_crosses': {'field': 'ask', 'level': 180.0, 'direction': 'at_or_above'}}}}}}
        self.database.add_event(datetime.datetime(2026, 10, 19, 14, 0, tzinfo=INDIA), 'entry-plan', 'parent_received', synthetic_type='plan', instrument_id=OPTION, detail=entry)
        self.measurement = StopSlippageMeasurement(self.database.connect, logging.getLogger('example'))

    def run(self):
        """Prints what each step gives, then writes.

        Returns:
            None: This method returns nothing.
        """
        start, end = self.measurement.day_bounds(datetime.date(2026, 10, 19), 1)
        rows = []
        for event in self.database.events:
            row = {}
            for column in EVENT_COLUMNS:
                row[column] = event[column]
            rows.append(row)
        parents = self.measurement.parents_from(rows)
        print(f'Parents: {sorted(parents)}')
        print(f'Entry plan trigger: {self.measurement.protective_trigger(rows[-1]["detail"])}')
        print(f'Stop trigger: {self.measurement.protective_trigger(rows[0]["detail"])}')
        print(f'The later stop fired at: {self.measurement.fired_at(rows[1]):%H:%M}')
        outcomes = self.measurement.fired_stops(parents, start, end)
        for outcome in outcomes:
            print(f'Fired: {outcome.parent_order_id} at {self.measurement.fired_at_of(outcome):%H:%M}')
            self.measurement.find_close(outcome, parents)
            print(f'  closed by {outcome.closed_by} at {outcome.average_price}, slip {outcome.slip()}')
        connection = self.database.connect()
        with connection.cursor() as cursor:
            print(f'Segments: {self.measurement.read_segments(cursor, [OPTION])}')
        written = self.measurement.write(start, end, outcomes)
        print(f'Wrote {written} rows; statements sent: {self.database.statements}')


if __name__ == '__main__':
    StepsAndWriteExample().run()
