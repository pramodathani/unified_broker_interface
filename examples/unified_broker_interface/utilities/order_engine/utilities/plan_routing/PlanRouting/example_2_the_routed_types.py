"""Lists the order types the engine runs as plans, which of them hold their orders by default, and the two it runs with classes of their own.

`ROUTED_TYPES` names every type a caller may ask for besides `simple` and `plan`; each runs as the preset `preset_name` gives, its own name except for `gtt`. `HOLDING_TYPES` names the ones whose orders are held in the virtual order book by default while `UNIFIED_BROKER_INTERFACE_API_ORDER_HOLD_LIMITS` is on. The registry, `SYNTHETIC_ORDER_CLASSES`, holds only the two types with classes of their own. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_routing/PlanRouting/example_2_the_routed_types.py
"""

from unified_broker_interface.utilities.order_engine.utilities import plan_routing
from unified_broker_interface.utilities.order_engine.utilities.plan_routing import (
    PlanRouting,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)


class TheRoutedTypesExample:
    """Prints the routed, holding and class-run types."""

    def run(self):
        """Prints the lists and the presets that differ from their type's name.

        Returns:
            None: This method returns nothing.
        """
        routed = plan_routing.ROUTED_TYPES
        print(f'{len(routed)} types run as plans, from {routed[0]} to {routed[-1]}')
        renamed = []
        for name in routed:
            if PlanRouting.preset_name(name) != name:
                renamed.append(f'{name} -> {PlanRouting.preset_name(name)}')
        print(f'presets with another name: {renamed}')
        print(f'{len(plan_routing.HOLDING_TYPES)} hold by default, such as {list(plan_routing.HOLDING_TYPES[:3])}')
        print(f'run with classes of their own: {sorted(SYNTHETIC_ORDER_CLASSES)}')
        print(f'simple or plan among the routed types: {"simple" in routed or "plan" in routed}')


if __name__ == '__main__':
    TheRoutedTypesExample().run()
