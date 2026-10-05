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
            RefusedRequestError: With HTTP 400 when the order is not a limit on an option with a strike and an expiry, follows its own instrument, or the option has already expired, which would otherwise leave the order armed for ever.
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
        if expires.timestamp() <= time.time():
            raise RefusedRequestError.refusal(
                f'the option expired at {expires:%Y-%m-%d %H:%M} India time, so the model has no premium to price it at',
                400,
                instrument_id=plan_order.instrument_id,
            )
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
        """The premium the volatility gives now, bounded and on the tick, and never worse than the body's price.

        The body's price is applied last, so a `lowest_price` above it on a buy, or a `highest_price` below it on a sell, cannot push the order past the worst price the caller accepts.

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
        premium = decimal.Decimal(str(round(model.price(float(self.volatility_now(memory)) / 100), 6)))
        worst = decimal.Decimal(str(plan_order.body['price']))
        worst = plan_order.view(quotes).rounded(worst, side) or worst
        premium = self.bounded(plan_order, premium, side, quotes)
        if premium is None:
            return None
        if side == 'BUY':
            return min(premium, worst)
        return max(premium, worst)

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

    def reason(self, watched, price, memory):
        """Why the order moved, for the event log.

        Args:
            watched (decimal.Decimal): The underlying's price.
            price (decimal.Decimal): The new premium.
            memory (dict): The pricing's memory, which holds a volatility the caller's change implied.

        Returns:
            str: The reason.
        """
        return f'at {self.volatility_now(memory)} volatility with the underlying at {watched}, the premium is {price}'

    def volatility_now(self, memory):
        """The volatility the order is priced at: the one a caller's price change implied, or the one it was placed with.

        Args:
            memory (dict): The pricing's memory.

        Returns:
            decimal.Decimal: The volatility, as a percentage.
        """
        if memory.get('volatility') is not None:
            return decimal.Decimal(str(memory['volatility']))
        return decimal.Decimal(str(self.volatility))

    def carry_on(self, plan_order, memory, leg, before, quotes, now):
        """Takes the volatility the caller's new price implies, so the order carries on at that volatility rather than snapping back.

        The implied volatility is found from the model with the underlying's price now. When the underlying has no price, the option has expired, or no volatility between 0.01% and 500% gives the caller's price, the volatility is left as it was and the next tick moves the order back.

        Args:
            plan_order (OrderContext): The plan order's context for this order, which reads quotes into prices.
            memory (dict): The pricing's memory, whose `volatility` is set in place.
            leg (OrderLeg): The order, holding the caller's new price.
            before (dict): What the leg held before, with `price`.
            quotes (dict): The quotes now, by instrument id.
            now (float): The Unix time of the change.

        Returns:
            str | None: What changed, for the event log, or None when nothing did.
        """
        if leg.price is None or leg.price == before.get('price') or memory.get('expires_at') is None:
            return None
        watched = self.watched_price(plan_order, quotes)
        if watched is None:
            return None
        model = self.model(memory, watched, now)
        if model is None:
            return None
        implied = model.implied_volatility(float(leg.price))
        if implied is None:
            return None
        volatility = round(decimal.Decimal(str(implied * 100)), 4)
        memory['volatility'] = str(volatility)
        return f'the caller moved the price to {leg.price}, which is {volatility} volatility with the underlying at {watched}, so the order carries on at that volatility'

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
