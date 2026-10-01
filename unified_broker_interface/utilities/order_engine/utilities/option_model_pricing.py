"""The pricing that prices an option from an implied volatility and keeps it current as the underlying moves."""

import datetime
import decimal
import math
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)
from unified_broker_interface.utilities.order_engine.utilities.follow_instrument_pricing import (
    FollowInstrumentPricing,
)

EXPIRES_AT = datetime.time(15, 30)
SECONDS_IN_A_YEAR = 365 * 24 * 60 * 60


class OptionModelPricing(FollowInstrumentPricing):
    """A plan order's pricing that turns a stated implied volatility into an option premium with the Black-76 model, re-priced as the underlying moves and expiry nears.

    It keeps the rules of today's volatility type. The watched instrument is the forward when it is a future; otherwise, such as for the index, the forward is the spot grown by `interest_rate` to expiry. The option's strike, expiry and kind are read from the catalogue when the plan is placed and kept in the pricing's memory. The body's own price is the worst the order will accept, so the premium is used only when it is better. It shares the bounds, the step and the moving of `FollowInstrumentPricing`.

    Attributes:
        volatility (decimal.Decimal): The implied volatility, as a percentage.
        interest_rate (decimal.Decimal): The yearly interest rate, as a percentage.
    """

    def __init__(self, instrument_id, volatility, interest_rate, lowest, highest, step_ticks):
        """Builds the pricing from settings the plan reader has already checked.

        Args:
            instrument_id (str): The underlying.
            volatility (decimal.Decimal): The implied volatility, as a percentage.
            interest_rate (decimal.Decimal): The yearly interest rate, as a percentage.
            lowest (decimal.Decimal | None): The lowest price, or None.
            highest (decimal.Decimal | None): The highest price, or None.
            step_ticks (int): The smallest move worth sending.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(instrument_id, None, lowest, highest, step_ticks)
        self.volatility = volatility
        self.interest_rate = interest_rate

    def prepared_memory(self, plan_order):
        """Reads the option's strike, expiry and kind, and whether the underlying is a future, when the plan is placed.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: The pricing's first memory.

        Raises:
            RefusedRequestError: With HTTP 400 when the order is not a limit on an option with a strike and an expiry, or follows its own instrument.
        """
        memory = super().prepared_memory(plan_order)
        instrument, _, _ = plan_order.placement.market_context(plan_order.instrument_id, False, False)
        identity = instrument.identity
        option_type = identity.get('option_type')
        strike = identity.get('strike_price')
        expiry = identity.get('expiry_date')
        if option_type not in ('CE', 'PE') or not strike or not expiry:
            raise RefusedRequestError.refusal(
                'option_model prices an option, and this instrument is not an option with a strike and an expiry',
                400,
                instrument_id=plan_order.instrument_id,
            )
        expiry_day = datetime.date.fromisoformat(str(expiry))
        expires = datetime.datetime.combine(expiry_day, EXPIRES_AT, moments.INDIA)
        watched, _, _ = plan_order.placement.market_context(self.instrument_id, False, False)
        memory['strike_price'] = float(strike)
        memory['expires_at'] = expires.timestamp()
        memory['is_call'] = option_type == 'CE'
        memory['underlying_is_forward'] = TradeableSegments.SHAPES.get(watched.bare_segment) == 'future'
        return memory

    def model(self, memory, watched, now):
        """The Black-76 model for the underlying's price now.

        Args:
            memory (dict): The pricing's memory, holding the option's terms.
            watched (decimal.Decimal): The underlying's price.
            now (float): The Unix time.

        Returns:
            Black76 | None: The model, or None once the option has expired.
        """
        years = (memory['expires_at'] - now) / SECONDS_IN_A_YEAR
        if years <= 0:
            return None
        rate = float(self.interest_rate) / 100
        forward = float(watched)
        if not memory.get('underlying_is_forward'):
            forward = forward * math.exp(rate * years)
        return Black76(forward, memory['strike_price'], years, rate, memory['is_call'])

    def premium(self, plan_order, memory, side, watched, quotes, now):
        """The premium the volatility gives now, no worse than the body's price, bounded and on the tick.

        Args:
            plan_order (OrderContext): The order's view of the plan order, whose body's price is the worst accepted.
            memory (dict): The pricing's memory.
            side (str): BUY or SELL.
            watched (decimal.Decimal): The underlying's price.
            quotes (dict): The quotes, for the order's own view.
            now (float): The Unix time.

        Returns:
            decimal.Decimal | None: The premium, or None once the option has expired.
        """
        model = self.model(memory, watched, now)
        if model is None:
            return None
        premium = decimal.Decimal(str(round(model.price(float(self.volatility) / 100), 6)))
        worst = decimal.Decimal(str(plan_order.body['price']))
        if side == 'BUY':
            premium = min(premium, worst)
        else:
            premium = max(premium, worst)
        return self.bounded(plan_order, premium, side, quotes)

    def target_price(self, plan_order, memory, side, watched, quotes, now):
        """Where the order should be: the premium for the underlying's price now.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The pricing's memory.
            side (str): BUY or SELL.
            watched (decimal.Decimal): The underlying's price now.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            decimal.Decimal | None: The premium, or None.
        """
        return self.premium(plan_order, memory, side, watched, quotes, now)

    def priced_body(self, plan_order, body, sending_side, quotes, memory):
        """The body as a limit at the premium the volatility gives now.

        Args:
            plan_order (PlanOrder): The plan order.
            body (dict): A copy of the order's body, changed in place.
            sending_side (str): BUY or SELL, the side the order is sent on.
            quotes (dict): The quotes, by instrument id.
            memory (dict): The pricing's memory, given `watched_start`.

        Returns:
            dict | None: The body, or None when the underlying has no price yet or the option has expired.
        """
        watched = self.watched_price(plan_order, quotes)
        if watched is None or memory.get('expires_at') is None:
            return None
        premium = self.premium(plan_order, memory, sending_side, watched, quotes, time.time())
        if premium is None:
            return None
        memory['watched_start'] = str(watched)
        body['order_type'] = 'LIMIT'
        body['price'] = str(premium)
        return body

    def reason(self, watched, price):
        """Why the order moved, for the event log.

        Args:
            watched (decimal.Decimal): The underlying's price.
            price (decimal.Decimal): The new premium.

        Returns:
            str: The reason.
        """
        return f'at {self.volatility} volatility with the underlying at {watched}, the premium is {price}'

    def described(self):
        """This pricing as a dry run shows it.

        Returns:
            dict: The settings.
        """
        return {
            'option_model': {
                'instrument_id': self.instrument_id,
                'volatility': str(self.volatility),
                'interest_rate': str(self.interest_rate),
                'lowest': None if self.lowest is None else str(self.lowest),
                'highest': None if self.highest is None else str(self.highest),
                'step_ticks': self.step_ticks,
            },
        }
