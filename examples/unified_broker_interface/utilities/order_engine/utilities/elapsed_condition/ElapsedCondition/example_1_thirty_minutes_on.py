"""Readies a condition that holds thirty minutes after the plan is placed, and asks it at three moments.

`ElapsedCondition.prepare` keeps the moment in the condition's memory, so a restart keeps the schedule; `is_met` holds from that moment on. It reads no quotes, so a clock tick can fire it. The moment is shown relative to when it was readied, so the output does not change from run to run. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/elapsed_condition/ElapsedCondition/example_1_thirty_minutes_on.py
"""

from unified_broker_interface.utilities.order_engine.utilities.elapsed_condition import (
    ElapsedCondition,
)


class ThirtyMinutesOnExample:
    """Asks a thirty-minute condition at three moments."""

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        condition = ElapsedCondition(30)
        memory = {}
        condition.prepare(None, memory)
        moment = memory['at']
        print(f'Reads quotes: {condition.needs_prices()}, watches: {condition.instruments()}')
        for offset in (-60, 0, 60):
            print(f'{offset} seconds from its moment: {condition.is_met(None, memory, {}, moment + offset, "BUY", "BUY")}')
        print(f'As a dry run shows it: {condition.described()}')


if __name__ == '__main__':
    ThirtyMinutesOnExample().run()
