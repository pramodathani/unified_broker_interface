"""Builds a Repeat join by hand of two orders that each also wait for a price, and reads one whose child is a join.

A copy that has a trigger of its own waits for both its trigger and its turn, so the plan reader joins the two with `all`. A Repeat join's child must be one order, because the copies are given triggers. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/repeat_part/RepeatPart/example_2_copies_with_their_own_trigger.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)
from unified_broker_interface.utilities.order_engine.utilities.repeat_part import (
    RepeatPart,
)


class CopiesWithTheirOwnTriggerExample:
    """Prints a repeat whose copies have triggers, and a refused one."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        reader = PlanReader('BUY')
        join = reader.read(
            {
                'repeat': {
                    'child': {
                        'order': {
                            'presets': [
                                {
                                    'limit_if_touched': {
                                        'trigger_price': 995,
                                        'limit_price': 995,
                                    },
                                },
                            ],
                        },
                    },
                    'times': 2,
                    'every_minutes': 10,
                },
            }
        )
        print(f'A repeat: {isinstance(join, RepeatPart)}')
        for part in join.order_parts():
            print(f'  {part.path}: {part.trigger.described()}')
        refused = PlanReader('BUY')
        refused.read(
            {
                'repeat': {
                    'child': {
                        'either': {},
                    },
                    'times': 2,
                    'every_minutes': 10,
                    'until': {
                        'time_after': '15:00',
                    },
                },
            }
        )
        for problem in refused.problems:
            print(f'  {problem["rule"]}: {problem["message"]}')
        print(f'Built by hand: {RepeatPart("root", [], 3, 5).expanded()}')


if __name__ == '__main__':
    CopiesWithTheirOwnTriggerExample().run()
