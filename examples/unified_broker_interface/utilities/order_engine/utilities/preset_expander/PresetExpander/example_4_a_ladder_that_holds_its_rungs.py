"""Shows the two shapes of the ladder preset: holding each rung until the market reaches it, and sending every rung at once.

The plan reader tells the expander whether the order the ladder is named in is held. When it is, or when the ladder's own `hold_limits` is true, the `ladder` preset stands for a join: a Using join of the `ladder` execution whose every rung is a `virtual_limit`, so each rung waits in the engine until the other side of the book reaches its own price. Otherwise, or with `hold_limits: false`, it stands for the `ladder` execution alone, which sends every rung at once. A held ladder refuses another execution and a post-only guard beside it, and `hold_limits` must be true or false. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/preset_expander/PresetExpander/example_4_a_ladder_that_holds_its_rungs.py
"""

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PresetExpander,
)


class LadderThatHoldsItsRungsExample:
    """Expands the ladder preset with and without holding, and three refusals."""

    def __init__(self):
        """Keeps the ladder's rung settings.

        Returns:
            None: This method returns nothing.
        """
        self.rungs = {
            'from_price': 1000,
            'to_price': 995,
            'steps': 3,
        }

    def show(self, label, settings, entry, held):
        """Prints whether the preset is a join and what it expands to.

        Args:
            label (str): What the case shows.
            settings (dict): The preset's settings.
            entry (dict): The rest of the order the preset is named in.
            held (bool): Whether the plan reader holds the order the preset is named in.

        Returns:
            None: This method returns nothing.
        """
        expander = PresetExpander('BUY', held)
        if expander.is_join('ladder', settings):
            tree = expander.expand_join('ladder', settings, entry, 'root.presets.0')
        else:
            tree = expander.expand('ladder', settings, 'root.presets.0')
        print(f'{label}: join={expander.is_join("ladder", settings)}')
        if expander.problems:
            for problem in expander.problems:
                print(f'  refused, {problem["rule"]}: {problem["message"]}')
            return
        print(f'  {tree}')

    def run(self):
        """Expands the six cases.

        Returns:
            None: This method returns nothing.
        """
        self.show('the order is held', dict(self.rungs), {}, True)
        self.show('the order is not held', dict(self.rungs), {}, False)
        self.show('the ladder says false in a held order', dict(self.rungs, hold_limits=False), {}, True)
        self.show(
            'held beside a twap',
            dict(self.rungs),
            {
                'presets': [
                    {
                        'twap': {
                            'slices': 2,
                            'over_minutes': 1,
                        },
                    },
                ],
            },
            True,
        )
        self.show(
            'held beside post_only',
            dict(self.rungs),
            {
                'presets': [
                    {
                        'post_only': {},
                    },
                ],
            },
            True,
        )
        self.show('hold_limits of no', dict(self.rungs, hold_limits='no'), {}, False)


if __name__ == '__main__':
    LadderThatHoldsItsRungsExample().run()
