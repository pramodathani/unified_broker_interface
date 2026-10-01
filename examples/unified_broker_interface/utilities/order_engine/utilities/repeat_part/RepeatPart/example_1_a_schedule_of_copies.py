"""Reads an accumulation of four purchases thirty minutes apart, and shows the copies the plan reader makes.

A Repeat join is read into one copy of its order per time. The first is sent at once and every later copy waits, through an `elapsed` trigger, for its turn. `RepeatPart` runs the copies as a Together join does, each with its own quantity, and its dry-run description keeps the schedule. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/repeat_part/RepeatPart/example_1_a_schedule_of_copies.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class AScheduleOfCopiesExample:
    """Reads an accumulation and prints its copies."""

    def run(self):
        """Prints the join and each copy's trigger.

        Returns:
            None: This method returns nothing.
        """
        reader = PlanReader('BUY')
        join = reader.read(
            {
                'order': {
                    'presets': [
                        {
                            'accumulation': {
                                'every_minutes': 30,
                                'purchases': 4,
                            },
                        },
                    ],
                },
            }
        )
        print(f'{type(join).__name__} of {join.times}, every {join.every_minutes} minutes, problems {reader.problems}')
        for part in join.order_parts():
            trigger = 'sent at once'
            if part.trigger is not None:
                trigger = part.trigger.described()
            print(f'  {part.path}: {trigger}, pricing {part.pricing.described()}')
        print(f'As a dry run shows it: {list(join.expanded()["repeat"])}')


if __name__ == '__main__':
    AScheduleOfCopiesExample().run()
