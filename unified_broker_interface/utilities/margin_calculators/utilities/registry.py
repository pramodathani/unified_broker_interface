"""The margin calculators, one per broker that has one."""

from unified_broker_interface.utilities.margin_calculators.dhan import (
    DhanMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.flattrade import (
    FlattradeMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.fyers import (
    FyersMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.groww import (
    GrowwMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.indmoney import (
    IndmoneyMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.kotak import (
    KotakMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.shoonya import (
    ShoonyaMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.wisdom_capital import (
    WisdomCapitalMarginCalculator,
)
from unified_broker_interface.utilities.margin_calculators.zerodha import (
    ZerodhaMarginCalculator,
)

MARGIN_CALCULATOR_CLASSES = [
    DhanMarginCalculator,
    FlattradeMarginCalculator,
    FyersMarginCalculator,
    GrowwMarginCalculator,
    IndmoneyMarginCalculator,
    KotakMarginCalculator,
    ShoonyaMarginCalculator,
    WisdomCapitalMarginCalculator,
    ZerodhaMarginCalculator,
]
