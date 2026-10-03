"""Routes a ladder and a bracket with holding on and off, and shows the `hold_limits` written beside each routed plan.

`PlanRouting` takes `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` as `hold_limits`. A routed order's `hold_limits` is moved from its settings to beside the plan, where the plan reader reads it for the whole request. When the caller does not say, it is true only for a type in `HOLDING_TYPES`, which is the ladder alone so far, and only while holding is on. The value is written into the order when it arrives, so the plan read again after a restart holds the same orders. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_3_holding_turned_off.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)


class HoldingTurnedOffExample:
    """Routes ladder and bracket intents with holding on and with it off."""

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
        """Prints the request's hold_limits and the preset settings each routed intent ends up with.

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
            (
                'sends a bracket',
                {
                    'type': 'bracket',
                    'stop_price': 990,
                    'stop_limit_price': 988,
                    'target_price': 1010,
                },
            ),
        ]
        for hold_limits in (True, False):
            routing = PlanRouting(
                [
                    'ladder',
                    'bracket',
                ],
                hold_limits,
            )
            for label, settings in cases:
                routed = routing.routed(self.intent(settings))
                synthetic = routed['body']['synthetic']
                preset = synthetic['plan']['order']['presets'][0]
                print(f'holding {"on" if hold_limits else "off"}, caller {label}: hold_limits={synthetic["hold_limits"]}, preset {preset}')


if __name__ == '__main__':
    HoldingTurnedOffExample().run()
