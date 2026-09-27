"""An order that sends a hedge in another instrument as it fills."""

import datetime
import decimal
import time

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.oto import OneTriggersOther
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.black76 import (
    Black76,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.position_closer import (
    PositionCloser,
)

EXPIRES_AT = datetime.time(15, 30)
SECONDS_IN_A_YEAR = 365 * 24 * 60 * 60


class AttachedHedge(OneTriggersOther):
    """An entry whose fills are hedged in another instrument, sized from what filled (the Atlas's G14).

    The hedge is `−ratio × filled` in units of the hedge instrument, rounded to its nearest whole lot. `ratio` covers a beta (a stock hedged with an index future), a pair trade's ratio, or a one-for-one hedge of a stock with its own future. With `delta_volatility` instead, the entry must be an option, and the ratio is its Black-76 delta at that volatility, worked out at the moment of each fill with the hedge instrument as the forward, so a Nifty option is delta-hedged with Nifty futures.

    A positive ratio hedges on the opposite side: a bought stock is hedged by a sold future. A negative one, such as a bought put's delta, hedges on the same side.

    The hedge grows with the entry. After each fill the target hedge is worked out again from everything filled so far, and a new hedge order is sent for the whole lots still missing, so no resting order is ever resized. Every hedge goes to the entry's broker, as a limit two ticks past the hedge instrument's other side.
    """

    SYNTHETIC_TYPE = 'attached_hedge'

    def hedge_instrument(self):
        """The instrument the hedge trades.

        Returns:
            str: The instrument id.

        Raises:
            RefusedRequestError: With HTTP 400 when it is missing or is the traded instrument itself.
        """
        hedge = self.parent.parameters.get('hedge_instrument_id')
        if not hedge:
            raise RefusedRequestError.refusal(
                'an attached hedge needs hedge_instrument_id, the instrument '
                'to hedge in',
                400,
            )
        if hedge == self.parent.instrument_id:
            raise RefusedRequestError.refusal(
                'an attached hedge trades another instrument, not the entry\'s '
                'own',
                400,
            )
        return hedge

    def number(self, name):
        """One numeric parameter, or None when it was not given.

        Args:
            name (str): The parameter's name.

        Returns:
            decimal.Decimal | None: The number.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a number.
        """
        value = self.parent.parameters.get(name)
        if value is None:
            return None
        try:
            return decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise RefusedRequestError.refusal(
                f'{name} must be a number, not {value!r}',
                400,
            )

    def check_sizing(self):
        """Checks that exactly one way of sizing the hedge was given.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when both or neither of `ratio` and `delta_volatility` are given, the ratio is zero, the volatility is not above zero, or delta sizing is asked for on something that is not an option.
        """
        ratio = self.number('ratio')
        volatility = self.number('delta_volatility')
        if (ratio is None) == (volatility is None):
            raise RefusedRequestError.refusal(
                'an attached hedge needs exactly one of ratio and '
                'delta_volatility',
                400,
            )
        if ratio is not None and ratio == 0:
            raise RefusedRequestError.refusal(
                'ratio must not be zero, since that hedges nothing',
                400,
            )
        if volatility is not None:
            if volatility <= 0:
                raise RefusedRequestError.refusal(
                    f'delta_volatility must be a percentage above zero, not '
                    f'{volatility}',
                    400,
                )
            self.option_details()

    def option_details(self):
        """The traded option's strike, expiry and kind, for delta sizing.

        Returns:
            tuple: The strike (float), the expiry as a Unix time (float) and whether it is a call (bool).

        Raises:
            RefusedRequestError: With HTTP 400 when the traded instrument is not an option.
        """
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        identity = instrument.identity
        option_type = identity.get('option_type')
        strike = identity.get('strike_price')
        expiry = identity.get('expiry_date')
        if option_type not in ('CE', 'PE') or not strike or not expiry:
            raise RefusedRequestError.refusal(
                'delta_volatility sizes the hedge by an option\'s delta, and '
                'this instrument is not an option with a strike and an expiry',
                400,
                instrument_id=self.parent.instrument_id,
            )
        expires = datetime.datetime.combine(
            datetime.date.fromisoformat(str(expiry)),
            EXPIRES_AT,
            moments.INDIA,
        )
        return float(strike), expires.timestamp(), option_type == 'CE'

    def hedge_ratio(self):
        """How many units of the hedge each filled unit needs, before its sign is applied.

        Returns:
            decimal.Decimal | None: The ratio, or None when the option has expired or the hedge instrument has no price to use as the forward.
        """
        ratio = self.number('ratio')
        if ratio is not None:
            return ratio
        strike, expires_at, is_call = self.option_details()
        years = (expires_at - time.time()) / SECONDS_IN_A_YEAR
        if years <= 0:
            return None
        instrument, quote, _ = self.placement.market_context(
            self.hedge_instrument(),
            True,
            False,
        )
        template = self.read_order(self.parent.body)
        tick_size = template.agreed_tick_size(instrument.handles)
        forward = MarketView(quote, tick_size).last()
        if forward is None:
            return None
        model = Black76(float(forward), strike, years, 0.0, is_call)
        delta = model.delta(float(self.number('delta_volatility')) / 100)
        return decimal.Decimal(str(round(delta, 6)))

    def lot_size(self, broker_name):
        """The hedge instrument's lot size at one broker.

        Args:
            broker_name (str): The broker.

        Returns:
            int: The lot size, 1 when the broker publishes none.
        """
        instrument, _, _ = self.placement.market_context(
            self.hedge_instrument(),
            False,
            False,
        )
        handle = instrument.handles.get(broker_name) or {}
        try:
            size = int(float(handle.get('lot_size') or 1))
        except (TypeError, ValueError):
            size = 1
        return max(size, 1)

    def run(self, intent, started_at):
        """Places the entry. The hedge follows its fills.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For a missing or bad hedge instrument or sizing, and for an order answered without calling a broker.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.hedge_instrument()
        self.check_sizing()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.save()
        body, status, _ = self.place_leg('entry', order, started_at)
        outcome = body.get('outcome')
        state = {
            'accepted': 'working',
            'rejected': 'rejected',
        }.get(outcome, 'failed')
        self.record_state(state, body.get('status_message'))
        self.save()
        body['parent_id'] = self.parent.parent_order_id
        return body, status

    def on_leg_update(self, leg, changes):
        """Sends the whole lots of hedge that everything filled so far still needs.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        if leg.role != 'entry':
            return
        filled = leg.filled_quantity or 0
        if filled < 1:
            return
        ratio = self.hedge_ratio()
        if ratio is None:
            self.logger.warning(
                f'Parent {self.parent.parent_order_id} could not size its '
                'hedge: the option has expired or the hedge has no price'
            )
            return
        entry_sign = 1 if leg.transaction_type == 'BUY' else -1
        wanted = -ratio * filled * entry_sign
        lot = self.lot_size(leg.broker)
        lots = (abs(wanted) / lot).to_integral_value(
            rounding=decimal.ROUND_HALF_UP,
        )
        target = int(lots) * lot
        placed = 0
        for other in self.parent.legs:
            if other.role == 'hedge' and other.state != 'rejected':
                placed = placed + (other.quantity or 0)
        missing = target - placed
        if missing < lot:
            return
        signed_missing = missing if wanted > 0 else -missing
        order = PositionCloser(self).closing_order(
            self.hedge_instrument(),
            decimal.Decimal(-signed_missing),
        )
        if order is None:
            self.logger.warning(
                f'Parent {self.parent.parent_order_id} could not price its '
                'hedge: the hedge instrument\'s book is empty'
            )
            return
        self.place_leg(
            'hedge',
            order,
            None,
            leg.broker,
            self.hedge_instrument(),
        )
        self.record_state(
            'protecting',
            f'{filled} filled, so the hedge is now {target} at a ratio of '
            f'{ratio}',
        )
        self.save()
