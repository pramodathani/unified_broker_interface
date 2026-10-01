"""Expands the presets that stand for a join of several orders into the plan trees they build.

Some presets are not one order's slot values but a whole join. `is_join` says which: `basket`, `oca`, `oto`, `oco`, `bracket` and `cover`, and `hidden_stop` once it has a backstop. `expand_join` builds the tree around the rest of the order the preset was named in, which becomes the join's main order: the entry of a bracket, a cover or an OTO, and the engine-side stop of a hidden stop with a backstop. An OCO protects a position already held, so it has no main order, and naming anything beside it is a problem. A basket and a one-cancels-all group make one order per candidate, each the rest of the order with the candidate's own instrument, side, quantity and price, so a basket named beside `post_only` is a basket of post-only orders. A stop and reverse is a join only with its default `sequential` method, and needs the side of the order that opened the position, so it is shown with an expander for a long: it closes the position held when the price is reached, and once the close is done opens the other side for what closed.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/preset_expander/PresetExpander/example_3_presets_that_stand_for_joins.py
"""

import json

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PresetExpander,
)


class PresetsThatStandForJoinsExample:
    """Expands each join preset around an entry and prints the tree.

    Attributes:
        expander (PresetExpander): The expander.
    """

    def __init__(self):
        """Builds the expander.

        Returns:
            None: This method returns nothing.
        """
        self.expander = PresetExpander()

    def show(self, name, settings, entry):
        """Expands one join preset and prints the tree and any problems.

        Args:
            name (str): The preset's name.
            settings (dict): Its settings.
            entry (dict): The rest of the order it was named in.

        Returns:
            None: This method returns nothing.
        """
        tree = self.expander.expand_join(name, settings, entry, 'root.presets.1')
        print(f'{name}: {json.dumps(tree, sort_keys=True)}')
        for problem in self.expander.problems:
            print(f"  {problem['path']} [{problem['rule']}]: {problem['message']}")

    def run(self):
        """Expands each join preset.

        Returns:
            None: This method returns nothing.
        """
        for name, settings in (
            ('bracket', {}),
            ('market_if_touched', {'trigger_price': 995}),
            ('hidden_stop', {'trigger_price': 995}),
            ('hidden_stop', {'trigger_price': 995, 'backstop_price': 980, 'backstop_limit_price': 978}),
        ):
            print(f'{name} with {settings} is a join: {self.expander.is_join(name, settings)}')
        entry = {
            'presets': [
                {
                    'market_if_touched': {
                        'trigger_price': 995,
                    },
                },
            ],
        }
        self.show('bracket', {'stop_price': 990, 'stop_limit_price': 988, 'target_price': 1010}, entry)
        self.show('cover', {'stop_price': 990, 'stop_limit_price': 988}, {})
        self.show('oto', {'then': {'transaction_type': 'SELL', 'price': 1010}}, {})
        self.show('oco', {'stop_price': 990, 'stop_limit_price': 988}, entry)
        self.show('hidden_stop', {'trigger_price': 995, 'backstop_price': 980, 'backstop_limit_price': 978}, {})
        candidates = [
            {
                'instrument_id': '11111111-1111-5111-8111-000000000001',
                'quantity': 10,
                'price': 1000,
            },
            {
                'instrument_id': '11111111-1111-5111-8111-000000000002',
                'transaction_type': 'SELL',
                'quantity': 5,
            },
        ]
        post_only = {
            'presets': [
                {
                    'post_only': {},
                },
            ],
        }
        self.show('basket', {'candidates': candidates, 'hedge_benefit': True}, post_only)
        self.show('oca', {'candidates': candidates}, {})
        print(f"stop_and_reverse with method double is a join: {self.expander.is_join('stop_and_reverse', {'method': 'double'})}")
        self.expander = PresetExpander('BUY')
        self.show('stop_and_reverse', {'trigger_price': 995}, {})


if __name__ == '__main__':
    PresetsThatStandForJoinsExample().run()
