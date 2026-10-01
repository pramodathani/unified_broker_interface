"""Shows a condition asked before it was readied, which never holds, and two conditions spacing a schedule.

Without `at` in its memory, `ElapsedCondition.is_met` says no, so an order whose plan was never readied cannot fire by accident. A Repeat join gives each copy after the first a condition of its own, the second `every_minutes` on and the third twice that. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/elapsed_condition/ElapsedCondition/example_2_not_readied.py
"""

from unified_broker_interface.utilities.order_engine.utilities.elapsed_condition import (
    ElapsedCondition,
)


class NotReadiedExample:
    """Prints a condition not readied, and a schedule's spacing."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        print(f'Not readied: {ElapsedCondition(5).is_met(None, {}, {}, 1790137800.0, "BUY", "BUY")}')
        second = {}
        third = {}
        ElapsedCondition(15).prepare(None, second)
        ElapsedCondition(30).prepare(None, third)
        print(f'The third copy waits {round((third["at"] - second["at"]) / 60)} minutes longer than the second')


if __name__ == '__main__':
    NotReadiedExample().run()
