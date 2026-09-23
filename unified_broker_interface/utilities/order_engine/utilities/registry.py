"""The synthetic order types, by the name a caller's `synthetic.type` selects them with."""

from unified_broker_interface.utilities.order_engine.bracket import Bracket
from unified_broker_interface.utilities.order_engine.accumulation import (
    Accumulation,
)
from unified_broker_interface.utilities.order_engine.atr_trail import AtrTrail
from unified_broker_interface.utilities.order_engine.basket import Basket
from unified_broker_interface.utilities.order_engine.candle_close_stop import (
    CandleCloseStop,
)
from unified_broker_interface.utilities.order_engine.chaser import Chaser
from unified_broker_interface.utilities.order_engine.cover import Cover
from unified_broker_interface.utilities.order_engine.cross_instrument import (
    CrossInstrument,
)
from unified_broker_interface.utilities.order_engine.exposure_hedge import (
    ExposureHedge,
)
from unified_broker_interface.utilities.order_engine.freeze_slicer import (
    FreezeSlicer,
)
from unified_broker_interface.utilities.order_engine.good_till_time import (
    GoodTillTime,
)
from unified_broker_interface.utilities.order_engine.daily_stop import DailyStop
from unified_broker_interface.utilities.order_engine.discretionary import (
    Discretionary,
)
from unified_broker_interface.utilities.order_engine.good_till_triggered import (
    GoodTillTriggered,
)
from unified_broker_interface.utilities.order_engine.grid import Grid
from unified_broker_interface.utilities.order_engine.hidden_stop import (
    HiddenStop,
)
from unified_broker_interface.utilities.order_engine.iceberg import Iceberg
from unified_broker_interface.utilities.order_engine.indicator_triggered import (
    IndicatorTriggered,
)
from unified_broker_interface.utilities.order_engine.implementation_shortfall import (
    ImplementationShortfall,
)
from unified_broker_interface.utilities.order_engine.ladder import Ladder
from unified_broker_interface.utilities.order_engine.limit_if_touched import (
    LimitIfTouched,
)
from unified_broker_interface.utilities.order_engine.legged_spread import (
    LeggedSpread,
)
from unified_broker_interface.utilities.order_engine.liquidity_seeking import (
    LiquiditySeeking,
)
from unified_broker_interface.utilities.order_engine.market_if_touched import (
    MarketIfTouched,
)
from unified_broker_interface.utilities.order_engine.oco import OneCancelsOther
from unified_broker_interface.utilities.order_engine.one_cancels_all import (
    OneCancelsAll,
)
from unified_broker_interface.utilities.order_engine.oto import OneTriggersOther
from unified_broker_interface.utilities.order_engine.peg import Peg
from unified_broker_interface.utilities.order_engine.participation import (
    Participation,
)
from unified_broker_interface.utilities.order_engine.post_only import PostOnly
from unified_broker_interface.utilities.order_engine.scale_out import ScaleOut
from unified_broker_interface.utilities.order_engine.scheduled import Scheduled
from unified_broker_interface.utilities.order_engine.simple import SimpleOrder
from unified_broker_interface.utilities.order_engine.square_off import SquareOff
from unified_broker_interface.utilities.order_engine.strategy_stop import (
    StrategyStop,
)
from unified_broker_interface.utilities.order_engine.time_stop import TimeStop
from unified_broker_interface.utilities.order_engine.trailing_entry import (
    TrailingEntry,
)
from unified_broker_interface.utilities.order_engine.trailing_stop import (
    TrailingStop,
)
from unified_broker_interface.utilities.order_engine.twap import Twap
from unified_broker_interface.utilities.order_engine.vwap import Vwap
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
    Peg.SYNTHETIC_TYPE: Peg,
    Chaser.SYNTHETIC_TYPE: Chaser,
    MarketIfTouched.SYNTHETIC_TYPE: MarketIfTouched,
    LimitIfTouched.SYNTHETIC_TYPE: LimitIfTouched,
    HiddenStop.SYNTHETIC_TYPE: HiddenStop,
    CrossInstrument.SYNTHETIC_TYPE: CrossInstrument,
    IndicatorTriggered.SYNTHETIC_TYPE: IndicatorTriggered,
    TrailingStop.SYNTHETIC_TYPE: TrailingStop,
    TrailingEntry.SYNTHETIC_TYPE: TrailingEntry,
    PostOnly.SYNTHETIC_TYPE: PostOnly,
    Discretionary.SYNTHETIC_TYPE: Discretionary,
    Vwap.SYNTHETIC_TYPE: Vwap,
    ImplementationShortfall.SYNTHETIC_TYPE: ImplementationShortfall,
    Participation.SYNTHETIC_TYPE: Participation,
    LiquiditySeeking.SYNTHETIC_TYPE: LiquiditySeeking,
    Iceberg.SYNTHETIC_TYPE: Iceberg,
    Grid.SYNTHETIC_TYPE: Grid,
    Basket.SYNTHETIC_TYPE: Basket,
    OneCancelsAll.SYNTHETIC_TYPE: OneCancelsAll,
    Cover.SYNTHETIC_TYPE: Cover,
    LeggedSpread.SYNTHETIC_TYPE: LeggedSpread,
    StrategyStop.SYNTHETIC_TYPE: StrategyStop,
    ExposureHedge.SYNTHETIC_TYPE: ExposureHedge,
    CandleCloseStop.SYNTHETIC_TYPE: CandleCloseStop,
    AtrTrail.SYNTHETIC_TYPE: AtrTrail,
    SquareOff.SYNTHETIC_TYPE: SquareOff,
    Accumulation.SYNTHETIC_TYPE: Accumulation,
    GoodTillTriggered.SYNTHETIC_TYPE: GoodTillTriggered,
    DailyStop.SYNTHETIC_TYPE: DailyStop,
}
