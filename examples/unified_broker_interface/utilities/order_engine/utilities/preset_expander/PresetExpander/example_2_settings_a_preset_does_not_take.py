"""Expands presets with settings they do not take, or without settings they need, and prints the problems.

A `PresetExpander` reports every setting a preset does not take rather than ignoring it, because a setting silently ignored is an order that does something other than what was asked. It also reports a setting a preset cannot work without, such as the time for `scheduled` or the watched instrument for `cross_instrument`, and an unknown `trigger_on` or `watch_field`. Each problem carries the preset's path, so the caller can find it in a large plan.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/preset_expander/PresetExpander/example_2_settings_a_preset_does_not_take.py
"""

from unified_broker_interface.utilities.order_engine.utilities.preset_expander import (
    PresetExpander,
)


class SettingsAPresetDoesNotTakeExample:
    """Expands five faulty presets and prints their problems.

    Attributes:
        expander (PresetExpander): The expander.
    """

    def __init__(self):
        """Builds the expander.

        Returns:
            None: This method returns nothing.
        """
        self.expander = PresetExpander()

    def show(self, name, settings):
        """Expands one preset and prints its problems.

        Args:
            name (str): The preset's name.
            settings (dict): Its settings.

        Returns:
            None: This method returns nothing.
        """
        self.expander.expand(name, settings, 'root.presets.0')
        print(f'{name} with {settings}:')
        for problem in self.expander.problems:
            print(f"  {problem['path']} [{problem['rule']}]: {problem['message']}")

    def run(self):
        """Expands each faulty preset.

        Returns:
            None: This method returns nothing.
        """
        self.show('simple', {'broker': 'zerodha'})
        self.show('scheduled', {})
        self.show('market_if_touched', {'trigger_price': 995, 'trigger_on': 'close'})
        self.show('indicator_triggered', {'watch_field': 'vwap', 'trigger_price': 1000, 'limit_price': 1000})
        self.show('hidden_stop', {'trigger_price': 990, 'backstop_price': 980})


if __name__ == '__main__':
    SettingsAPresetDoesNotTakeExample().run()
