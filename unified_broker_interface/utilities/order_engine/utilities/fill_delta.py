"""An order's size as the delta of the option the plan traded, times what the first plan of a Then join filled, in whole lots."""

import datetime
import decimal
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)
from unified_broker_interface.utilities.order_engine.utilities.fill_sizing import (
    FillSizing,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)

EXPIRES_AT = datetime.time(15, 30)
SECONDS_IN_A_YEAR = 365 * 24 * 60 * 60


class FillDelta(FillSizing):
    """A plan order that delta-hedges the option the plan traded: the option's delta times what the first plan has filled, in units of this order's instrument.

    It keeps today's attached hedge's `delta_volatility` sizing. The option is the plan's own instrument, the body's, which must be an option with a strike and an expiry. Its Black-76 delta is worked out at `volatility`, at the moment of each fill, with this order's instrument as the forward, so a Nifty option is delta-hedged with Nifty futures. The size is the delta's size; whether the hedge buys or sells is the `against_delta` side's decision, since a put's delta is negative.

    Attributes:
        volatility (decimal.Decimal): The volatility, as a percentage above zero.
        whole_lots (bool): Whether the size is rounded to the nearest whole lot.
    """

    def __init__(self, volatility, whole_lots):
        """Builds the sizing from settings the plan reader has already checked.

        Args:
            volatility (decimal.Decimal): The volatility, as a percentage.
            whole_lots (bool): Whether to round to whole lots.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(whole_lots)
        self.volatility = volatility

    def option_details(self, context):
        """The plan's option's strike, expiry and kind.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            tuple: The strike (float), the expiry as a Unix time (float) and whether it is a call (bool).

        Raises:
            RefusedRequestError: With HTTP 400 when the plan's instrument is not an option.
        """
        option_id = context.parent.instrument_id
        instrument, _, _ = context.placement.market_context(option_id, False, False)
        identity = instrument.identity
        option_type = identity.get('option_type')
        strike = identity.get('strike_price')
        expiry = identity.get('expiry_date')
        if option_type not in ('CE', 'PE') or not strike or not expiry:
            raise RefusedRequestError.refusal(
                'delta_volatility sizes the hedge by an option\'s delta, and this instrument is not an option with a strike and an expiry',
                400,
                instrument_id=option_id,
            )
        expires = datetime.datetime.combine(
            datetime.date.fromisoformat(str(expiry)),
            EXPIRES_AT,
            moments.INDIA,
        )
        return float(strike), expires.timestamp(), option_type == 'CE'

    def check(self, context):
        """Refuses the plan when its instrument is not an option.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when the plan's instrument is not an option.
        """
        self.option_details(context)

    def is_call(self, context):
        """Whether the plan's option is a call, whose delta is positive.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            bool: True for a call, False for a put.
        """
        _, _, is_call = self.option_details(context)
        return is_call

    def delta(self, context):
        """The option's delta now, with this order's instrument's last price as the forward.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            decimal.Decimal | None: The delta, or None when the option has expired or the forward has no price.
        """
        strike, expires_at, is_call = self.option_details(context)
        years = (expires_at - time.time()) / SECONDS_IN_A_YEAR
        if years <= 0:
            return None
        _, quote, _ = context.placement.market_context(context.instrument_id, True, False)
        forward = MarketView(quote, context.tick_size()).last()
        if forward is None:
            return None
        model = Black76(float(forward), strike, years, 0.0, is_call)
        delta = model.delta(float(self.volatility) / 100)
        return decimal.Decimal(str(round(delta, 6)))

    def scaled(self, context, filled):
        """The size for what the first plan has filled.

        Args:
            context (OrderContext): The order's view of the plan order.
            filled (int): What the first plan has filled.

        Returns:
            int | None: The size, or None when no delta can be worked out now, so the size is left as it was.
        """
        delta = self.delta(context)
        if delta is None:
            context.plan_order.logger.warning(f'Parent {context.parent.parent_order_id} could not size its hedge: the option has expired or the hedge has no price')
            return None
        return self.rounded(context, abs(delta) * decimal.Decimal(filled))

    def described(self):
        """This sizing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'parent_fill_delta': {
                'volatility': str(self.volatility),
                'whole_lots': self.whole_lots,
            },
        }
