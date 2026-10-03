"""Shows how intents for a grid, a gtt order and a simple order are rewritten before the engine runs them.

`PlanRouting.routed` turns an intent for any type in `ROUTED_TYPES` into a `plan` whose one order names that type's preset with the caller's settings, keeping the original name as `routed_from` and writing `hold_limits` beside the plan. A `gtt` order runs as the `good_till_triggered` preset, which `preset_name` says. A `simple` order is left as it is, since the engine runs it with a class of its own. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_1_routing_two_types.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)


class RoutingTwoTypesExample:
    """Rewrites three intents."""

    def intent(self, settings):
        """An intent for a buy of five RELIANCE with the given synthetic settings.

        Args:
            settings (dict): The `synthetic` object, with its `type`.

        Returns:
            dict: The intent.
        """
        return {
            'intent_id': 'intent-1',
            'instrument_id': 'RELIANCE',
            'synthetic_type': settings['type'],
            'body': {
                'transaction_type': 'BUY',
                'order_type': 'LIMIT',
                'quantity': 5,
                'price': '1000',
                'synthetic': settings,
            },
        }

    def run(self):
        """Prints each intent's type and synthetic object after routing.

        Returns:
            None: This method returns nothing.
        """
        routing = PlanRouting(False)
        print(f'gtt runs as {routing.preset_name("gtt")}, grid as {routing.preset_name("grid")}')
        intents = [
            self.intent(
                {
                    'type': 'grid',
                    'levels': 2,
                    'step_points': 5,
                    'most_inventory': 20,
                },
            ),
            self.intent(
                {
                    'type': 'gtt',
                    'trigger_price': 995,
                    'limit_price': 990,
                },
            ),
            self.intent(
                {
                    'type': 'simple',
                },
            ),
        ]
        for intent in intents:
            routed = routing.routed(intent)
            print(f'{intent["synthetic_type"]} -> {routed["synthetic_type"]}: {routed["body"]["synthetic"]}')


if __name__ == '__main__':
    RoutingTwoTypesExample().run()
