"""Expands the presets that stand for a join of several orders into the plan trees they build.

Some presets are not one order's slot values but a whole join. `is_join` says which: `oto`, `oco`, `bracket` and `cover`, and `hidden_stop` once it has a backstop. `expand_join` builds the tree around the rest of the order the preset was named in, which becomes the join's main order: the entry of a bracket, a cover or an OTO, and the engine-side stop of a hidden stop with a backstop. An OCO protects a position already held, so it has no main order, and naming anything beside it is a problem.

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


if __name__ == '__main__':
    PresetsThatStandForJoinsExample().run()
