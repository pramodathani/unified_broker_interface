"""Expands each preset that stands for one order into the slot values it stands for.

A `PresetExpander` turns a preset, named after an existing synthetic type and taking that type's settings, into slot values written the way a caller would write them by hand, which the plan reader then checks. This program expands every such preset with typical settings and prints what each becomes, so the meaning of a preset can be read in one place. The presets that stand for a join of several orders are shown in the third program.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/preset_expander/PresetExpander/example_1_what_each_preset_stands_for.py
"""

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    JOIN_PRESET_NAMES,
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
        """Builds the expander for an order opened with a buy, which a trailing stop's activation needs.

        Returns:
            None: This method returns nothing.
        """
        self.expander = PresetExpander('BUY')

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
            'trailing_stop': {
                'trail_points': 5,
                'stop_limit_offset': 1,
                'activate_at': 1010,
            },
            'trailing_entry': {
                'trail_percent': 0.5,
                'stop_limit_offset': 1,
            },
            'iceberg': {
                'slice_quantity': 75,
                'randomise_percent': 10,
            },
            'twap': {
                'slices': 4,
                'over_minutes': 20,
            },
            'vwap': {
                'slices': 6,
                'over_minutes': 90,
            },
            'implementation_shortfall': {
                'slices': 5,
                'over_minutes': 10,
                'urgency': 0.8,
            },
        }
        for name in PRESET_NAMES:
            if name in JOIN_PRESET_NAMES:
                continue
            slots = self.expander.expand(name, settings[name], f'root.presets.{name}')
            print(f'{name}: {slots}')
            print(f'  problems: {self.expander.problems}')


if __name__ == '__main__':
    WhatEachPresetStandsForExample().run()
