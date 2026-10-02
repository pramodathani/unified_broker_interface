"""Lists the fixed types the switch-over can run as plans, and shows a name it refuses.

`PlanRouting.routable_names` is every fixed synthetic type with a preset to run it as; `simple` and `plan` are left out, since they are not switched. A name that is not one of them, such as a misspelling, stops the engine from starting with a `ValueError` naming the ones that can be routed, rather than being silently ignored. With the setting empty, as it is by default, nothing is routed. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_2_what_can_be_routed.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)


class WhatCanBeRoutedExample:
    """Lists the routable types, builds an empty routing and refuses a bad name."""

    def run(self):
        """Prints the routable types and the refusal.

        Returns:
            None: This method returns nothing.
        """
        names = PlanRouting.routable_names()
        print(f'{len(names)} types can be routed, from {names[0]} to {names[-1]}; simple among them: {"simple" in names}')
        empty = PlanRouting(
            [
                '',
            ],
        )
        intent = {
            'synthetic_type': 'grid',
            'body': {},
        }
        print(f'with the setting empty, a grid intent is left alone: {empty.routed(intent) is intent}')
        try:
            PlanRouting(
                [
                    'grdi',
                ],
            )
        except ValueError as error:
            print(f'refused: {str(error)[:120]}...')


if __name__ == '__main__':
    WhatCanBeRoutedExample().run()
