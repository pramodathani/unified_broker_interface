"""The synthetic order types, by the name a caller's `synthetic.type` selects them with."""

from unified_broker_interface.utilities.order_engine.bracket import Bracket
from unified_broker_interface.utilities.order_engine.freeze_slicer import (
    FreezeSlicer,
)
from unified_broker_interface.utilities.order_engine.ladder import Ladder
from unified_broker_interface.utilities.order_engine.oco import OneCancelsOther
from unified_broker_interface.utilities.order_engine.oto import OneTriggersOther
from unified_broker_interface.utilities.order_engine.simple import SimpleOrder

SYNTHETIC_ORDER_CLASSES = {
    SimpleOrder.SYNTHETIC_TYPE: SimpleOrder,
    FreezeSlicer.SYNTHETIC_TYPE: FreezeSlicer,
    Ladder.SYNTHETIC_TYPE: Ladder,
    OneTriggersOther.SYNTHETIC_TYPE: OneTriggersOther,
    OneCancelsOther.SYNTHETIC_TYPE: OneCancelsOther,
    Bracket.SYNTHETIC_TYPE: Bracket,
}
