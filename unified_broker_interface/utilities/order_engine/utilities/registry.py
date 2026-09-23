"""The synthetic order types, by the name a caller's `synthetic.type` selects them with."""

from unified_broker_interface.utilities.order_engine.bracket import Bracket
from unified_broker_interface.utilities.order_engine.freeze_slicer import (
    FreezeSlicer,
)
from unified_broker_interface.utilities.order_engine.good_till_time import (
    GoodTillTime,
)
from unified_broker_interface.utilities.order_engine.ladder import Ladder
from unified_broker_interface.utilities.order_engine.oco import OneCancelsOther
from unified_broker_interface.utilities.order_engine.oto import OneTriggersOther
from unified_broker_interface.utilities.order_engine.scale_out import ScaleOut
from unified_broker_interface.utilities.order_engine.scheduled import Scheduled
from unified_broker_interface.utilities.order_engine.simple import SimpleOrder
from unified_broker_interface.utilities.order_engine.time_stop import TimeStop
from unified_broker_interface.utilities.order_engine.twap import Twap
from unified_broker_interface.utilities.order_engine.two_sided_breakout import (
    TwoSidedBreakout,
)

SYNTHETIC_ORDER_CLASSES = {
    SimpleOrder.SYNTHETIC_TYPE: SimpleOrder,
    FreezeSlicer.SYNTHETIC_TYPE: FreezeSlicer,
    Ladder.SYNTHETIC_TYPE: Ladder,
    OneTriggersOther.SYNTHETIC_TYPE: OneTriggersOther,
    OneCancelsOther.SYNTHETIC_TYPE: OneCancelsOther,
    Bracket.SYNTHETIC_TYPE: Bracket,
    ScaleOut.SYNTHETIC_TYPE: ScaleOut,
    TwoSidedBreakout.SYNTHETIC_TYPE: TwoSidedBreakout,
    Scheduled.SYNTHETIC_TYPE: Scheduled,
    GoodTillTime.SYNTHETIC_TYPE: GoodTillTime,
    TimeStop.SYNTHETIC_TYPE: TimeStop,
    Twap.SYNTHETIC_TYPE: Twap,
}
