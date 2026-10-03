"""Routes the ladder type with holding on and off, and shows when `hold_limits: false` is written into the routed order.

`PlanRouting` takes `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` as `hold_limits`. With it on, a routed ladder keeps the caller's settings, so its preset holds each rung. With it off, a routed ladder that does not say is given `hold_limits: false`, so its rungs are sent at once, and a caller who says `true` keeps it. The value is written into the order when it arrives, so the plan read again after a restart has the same shape. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_3_holding_turned_off.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)


class HoldingTurnedOffExample:
    """Routes three ladder intents with holding on and with it off."""

    def intent(self, settings):
        """An intent for a buy of nine RELIANCE with the given synthetic settings.

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
                'quantity': 9,
                'price': '1000',
                'synthetic': settings,
            },
        }

    def run(self):
        """Prints the preset settings each routed intent ends up with.

        Returns:
            None: This method returns nothing.
        """
        ladder = {
            'type': 'ladder',
            'from_price': 1000,
            'to_price': 995,
            'steps': 3,
        }
        cases = [
            (
                'says nothing',
                dict(ladder),
            ),
            (
                'says false',
                dict(ladder, hold_limits=False),
            ),
            (
                'says true',
                dict(ladder, hold_limits=True),
            ),
        ]
        for hold_limits in (True, False):
            routing = PlanRouting(
                [
                    'ladder',
                ],
                hold_limits,
            )
            for label, settings in cases:
                routed = routing.routed(self.intent(settings))
                preset = routed['body']['synthetic']['plan']['order']['presets'][0]['ladder']
                print(f'holding {"on" if hold_limits else "off"}, caller {label}: {preset}')


if __name__ == '__main__':
    HoldingTurnedOffExample().run()
