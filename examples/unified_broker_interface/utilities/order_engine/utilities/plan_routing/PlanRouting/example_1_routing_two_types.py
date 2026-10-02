"""Routes the grid and gtt types to their plan presets and shows how an intent of each, and of a type left alone, is rewritten.

`PlanRouting` is built from the names in `UNIFIED_BROKER_INTERFACE_API_ORDER_PLAN_TYPES`. `routed` leaves an intent for a type not named untouched, and turns one for a named type into a `plan` whose one order names that type's preset with the caller's settings, keeping the original name as `routed_from`. A `gtt` order runs as the `good_till_triggered` preset, which `preset_name` says. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_1_routing_two_types.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)


class RoutingTwoTypesExample:
    """Routes two types and rewrites three intents."""

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
        routing = PlanRouting(
            [
                'grid',
                'gtt',
                '',
            ],
        )
        print(f'routed types: {routing.type_names}; gtt runs as {routing.preset_name("gtt")}, grid as {routing.preset_name("grid")}')
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
                    'type': 'bracket',
                    'stop_price': 990,
                    'stop_limit_price': 988,
                },
            ),
        ]
        for intent in intents:
            routed = routing.routed(intent)
            print(f'{intent["synthetic_type"]} -> {routed["synthetic_type"]}: {routed["body"]["synthetic"]}')


if __name__ == '__main__':
    RoutingTwoTypesExample().run()
