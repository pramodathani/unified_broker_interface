"""The broker selection algorithms, by the name configuration selects them with."""

from unified_broker_interface.utilities.broker_selection.fixed_priority import (
    FixedPrioritySelector,
)
from unified_broker_interface.utilities.broker_selection.lowest_cost import (
    LowestCostSelector,
)
from unified_broker_interface.utilities.broker_selection.round_robin import (
    RoundRobinSelector,
)

BROKER_SELECTOR_CLASSES = {
    LowestCostSelector.NAME: LowestCostSelector,
    RoundRobinSelector.NAME: RoundRobinSelector,
    FixedPrioritySelector.NAME: FixedPrioritySelector,
}
