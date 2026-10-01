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
            'participation': {
                'participation_percent': 10,
            },
            'liquidity_seeking': {
                'limit_price': 1000.10,
                'minimum_quantity': 10,
            },
            'peg': {
                'reference': 'mid',
                'cap_price': 1000.10,
            },
            'chaser': {
                'step_seconds': 3,
                'cross_after_seconds': 60,
            },
            'post_only': {
                'on_crossing': 'rest',
            },
            'underlying_peg': {
                'watch_instrument_id': '11111111-1111-5111-8111-000000000010',
                'delta': 0.5,
                'highest_price': 250,
            },
            'volatility': {
                'watch_instrument_id': '11111111-1111-5111-8111-000000000010',
                'volatility': 12.5,
                'interest_rate': 6.5,
            },
            'discretionary': {
                'discretion_points': 0.25,
                'discretion_quantity': 4,
            },
            'atr_trail': {
                'trail_points': 10,
                'stop_limit_offset': 2,
                'periods': 14,
                'atr_multiple': 2,
            },
            'stepped_stop': {
                'entry_price': 1000,
                'stop_price': 990,
                'stop_limit_offset': 2,
                'rules': [
                    {
                        'gain': 20,
                        'stop_at_gain': 0,
                    },
                ],
            },
            'good_till_time': {
                'until_time': '14:30',
                'at_expiry': 'market',
            },
            'time_stop': {
                'minutes': 20,
            },
            'close_on_trigger': {
                'trigger_price': 995,
            },
            'candle_close_stop': {
                'trigger_price': 995,
                'bar_minutes': 15,
            },
            'ladder': {
                'from_price': 995,
                'to_price': 1000,
                'steps': 3,
            },
            'freeze_slicer': {},
            'closing_price': {
                'slices': 4,
            },
            'opening_auction': {
                'at_time': '09:02:00',
            },
            'virtual_limit': {
                'paper': True,
            },
            'grid': {
                'levels': 2,
                'step_points': 5,
                'most_inventory': 20,
            },
            'two_sided_quote': {
                'half_spread_points': 1,
                'most_inventory': 30,
            },
            'scale_with_profit_taker': {
                'from_price': 1000,
                'to_price': 990,
                'steps': 3,
                'profit_points': 4,
            },
            'scale_out_exits': {
                'stop_price': 990,
                'stop_limit_price': 988,
                'target_prices': [
                    1010,
                    1020,
                ],
            },
            'exposure_hedge': {
                'watched': [
                    {
                        'instrument_id': 'RELIANCE',
                    },
                ],
                'hedge_instrument_id': 'RELIANCE',
                'lower_band': -10,
                'upper_band': 10,
            },
            'account_conditional': {
                'account_field': 'day_pnl',
                'account_level': -5000,
                'trigger_direction': 'at_or_below',
                'action': 'cancel',
            },
            'daily_stop': {
                'stop_price': 990,
                'stop_limit_price': 988,
            },
            'good_till_triggered': {
                'trigger_price': 995,
                'limit_price': 990,
                'valid_days': 30,
            },
            'square_off': {
                'at_time': '15:10',
            },
            'stop_and_reverse': {
                'trigger_price': 995,
                'method': 'double',
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
