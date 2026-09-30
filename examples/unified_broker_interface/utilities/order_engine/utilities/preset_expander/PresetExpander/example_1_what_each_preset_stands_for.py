"""Expands each preset a plan can use into the slot values it stands for.

A `PresetExpander` turns a preset, named after an existing synthetic type and taking that type's settings, into slot values written the way a caller would write them by hand, which the plan reader then checks. This program expands every preset available so far with typical settings and prints what each becomes, so the meaning of a preset can be read in one place.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/preset_expander/PresetExpander/example_1_what_each_preset_stands_for.py
"""

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PRESET_NAMES,
    PresetExpander,
)

FUTURE_ID = '11111111-1111-5111-8111-000000000004'


class WhatEachPresetStandsForExample:
    """Expands every preset and prints its slot values.

    Attributes:
        expander (PresetExpander): The expander.
    """

    def __init__(self):
        """Builds the expander.

        Returns:
            None: This method returns nothing.
        """
        self.expander = PresetExpander()

    def run(self):
        """Prints each preset's slot values.

        Returns:
            None: This method returns nothing.
        """
        settings = {
            'simple': {},
            'market_if_touched': {
                'trigger_price': 995,
            },
            'limit_if_touched': {
                'trigger_price': 995,
                'limit_price': 996,
                'trigger_on': 'double_last',
            },
            'scheduled': {
                'at_time': '10:00',
            },
            'indicator_triggered': {
                'watch_field': 'average_price',
                'trigger_price': 1001,
                'trigger_direction': 'at_or_above',
                'limit_price': 1001.5,
            },
            'cross_instrument': {
                'watch_instrument_id': FUTURE_ID,
                'trigger_price': 1010,
                'limit_price': 1000,
            },
            'hidden_stop': {
                'trigger_price': 990,
                'buffer_ticks': 3,
            },
        }
        for name in PRESET_NAMES:
            slots = self.expander.expand(name, settings[name], f'root.presets.{name}')
            print(f'{name}: {slots}')
            print(f'  problems: {self.expander.problems}')


if __name__ == '__main__':
    WhatEachPresetStandsForExample().run()
