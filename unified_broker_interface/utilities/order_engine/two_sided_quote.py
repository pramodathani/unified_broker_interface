"""A bid and an offer kept around a fair price, leaning away from what has been bought or sold."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.grid import Grid

FAIR_PRICES = (
    'mid',
    'last',
)
QUOTE_SIDES = {
    'bid': 'BUY',
    'ask': 'SELL',
}


class TwoSidedQuote(Grid):
    """One buy and one sell limit kept around a fair price, re-priced as it moves (the Atlas's G16, a market-making pair).

    Each second the fair price is read, the mid between the best bid and offer by default, and the bid is kept `half_spread_points` below it and the ask the same distance above. A quote is only modified once its price has moved by at least `step_ticks`, because this type sends more modifies than any other and each one counts towards the day's order messages and the order-to-trade ratio.

    **Inventory skews both quotes.** For every order's worth held, both prices move `skew_ticks` against the position: a long lowers both, so its ask is more likely to be taken and its bid less. When one side fills, the other is not cancelled but re-priced by that skew on the next tick, and the filled side is quoted again. Once the net position reaches `most_inventory`, the side that would add to it is cancelled and not quoted again until the position comes back, as a grid does.

    The order's `quantity` is the size of each quote.
    """

    SYNTHETIC_TYPE = 'two_sided_quote'
    WANTS_PRICES = True

    def read_positive(self, name, required):
        """One number above zero from the parameters.

        Args:
            name (str): The parameter's name.
            required (bool): Whether it must be given.

        Returns:
            decimal.Decimal | None: The number, or None when it was not given and is not required.

        Raises:
            RefusedRequestError: With HTTP 400 when it is required and missing, or is not a number above zero.
        """
        value = self.parent.parameters.get(name)
        if value is None and not required:
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            number = None
        if value is None or number is None or not number.is_finite() or number <= 0:
            raise RefusedRequestError.refusal(
                f'a two-sided quote needs {name} as a number above zero, not '
                f'{value!r}',
                400,
            )
        return number

    def read_whole(self, name, default, lowest):
        """One whole-number parameter.

        Args:
            name (str): The parameter's name.
            default (int): The value when it is not given.
            lowest (int): The smallest value allowed.

        Returns:
            int: The number.

        Raises:
            RefusedRequestError: With HTTP 400 when it is not a whole number at or above `lowest`.
        """
        value = self.parent.parameters.get(name, default)
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = lowest - 1
        if number < lowest:
            raise RefusedRequestError.refusal(
                f'{name} must be a whole number of at least {lowest}, not '
                f'{value!r}',
                400,
            )
        return number

    def read_fair_price_kind(self):
        """Which price the quotes are kept around.

        Returns:
            str: One of `FAIR_PRICES`.

        Raises:
            RefusedRequestError: With HTTP 400 for another value.
        """
        kind = self.parent.parameters.get('fair_price') or 'mid'
        if kind not in FAIR_PRICES:
            raise RefusedRequestError.refusal(
                f'fair_price must be one of {", ".join(FAIR_PRICES)}, not '
                f'{kind!r}',
                400,
            )
        return kind

    def wanted_prices(self, view):
        """Where the bid and the ask belong now.

        Args:
            view (MarketView): The live quote.

        Returns:
            dict | None: `bid` and `ask` prices (decimal.Decimal), or None when the quote does not carry the fair price.
        """
        if self.read_fair_price_kind() == 'mid':
            fair = view.mid()
        else:
            fair = view.last()
        tick_size = self.tick_size()
        if fair is None or not tick_size:
            return None
        order = self.read_order(self.parent.body)
        held = decimal.Decimal(self.inventory()) / decimal.Decimal(order.quantity)
        shift = held * self.read_whole('skew_ticks', 0, 0) * tick_size
        half_spread = self.read_positive('half_spread_points', True)
        bid = view.rounded(fair - half_spread - shift, 'BUY')
        ask = view.rounded(fair + half_spread - shift, 'SELL')
        if bid is None or ask is None or bid <= 0:
            return None
        return {
            'bid': bid,
            'ask': ask,
        }

    def live_quote(self, role):
        """The resting order on one side, if there is one.

        Args:
            role (str): `bid` or `ask`.

        Returns:
            OrderLeg | None: The leg.
        """
        for leg in self.parent.legs:
            if leg.role == role and not leg.is_finished():
                return leg
        return None

    def run(self, intent, started_at):
        """Places the bid and the ask around the fair price now.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a bad spread, skew, step, cap or fair price, and 503 when there is no tick size or the quote does not carry the fair price.
        """
        order = self.concrete_order(self.read_order(self.parent.body))
        self.read_positive('half_spread_points', True)
        self.read_whole('skew_ticks', 0, 0)
        self.read_whole('step_ticks', 1, 1)
        self.read_most_inventory()
        self.read_fair_price_kind()

        if order.dry_run:
            prepared = self.placement.prepare(
                order,
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        _, quote, _ = self.placement.market_context(
            self.parent.instrument_id,
            True,
            False,
        )
        prices = self.wanted_prices(self.view({self.parent.instrument_id: quote}))
        if prices is None:
            raise RefusedRequestError.refusal(
                'a two-sided quote is kept around the fair price, and the '
                'live quote does not carry it yet',
                503,
                instrument_id=self.parent.instrument_id,
            )
        self.record_received()
        self.save()
        answers = []
        broker_name = None
        for role, side in QUOTE_SIDES.items():
            body, status, _ = self.place_leg(
                role,
                self.level_order(order, side, prices[role]),
                started_at,
                broker_name,
            )
            if broker_name is None:
                broker_name = body.get('broker')
            answers.append((side, prices[role], body, status))
        return self.settle(answers, broker_name, (prices['bid'] + prices['ask']) / 2)

    def on_leg_update(self, leg, changes):
        """Leaves a filled quote to the next price tick, which quotes that side again and re-prices the other by the new skew.

        Args:
            leg (OrderLeg): The leg that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """

    def on_price_tick(self, quotes, now):
        """Keeps both quotes where they belong, re-quoting a filled side and pulling the side that would pass the inventory cap.

        Args:
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when any order was placed, moved or cancelled.
        """
        if self.parent.is_terminal():
            return False
        view = self.view(quotes)
        if view.is_stale():
            return False
        prices = self.wanted_prices(view)
        if prices is None:
            return False
        order = self.concrete_order(self.read_order(self.parent.body))
        at_cap = self.past_its_cap()
        adding = self.adding_side()
        step = self.tick_size() * self.read_whole('step_ticks', 1, 1)
        acted = False
        for role, side in QUOTE_SIDES.items():
            leg = self.live_quote(role)
            blocked = at_cap and side == adding
            if blocked:
                if leg is not None and leg.broker_order_id is not None:
                    acted = self.cancel_leg(
                        leg,
                        f'the quote is holding {self.inventory()}, its whole '
                        'allowance, so it stops quoting that side',
                    ) or acted
                continue
            if leg is None:
                self.place_leg(
                    role,
                    self.level_order(order, side, prices[role]),
                    None,
                    self.chosen_broker(),
                )
                acted = True
                continue
            if leg.broker_order_id is None or leg.price is None:
                continue
            current = decimal.Decimal(str(leg.price))
            if abs(prices[role] - current) < step:
                continue
            acted = self.reprice_leg(
                leg,
                prices[role],
                None,
                f'the fair price moved, so the {role} goes to {prices[role]}',
            ) or acted
        if acted:
            self.save()
        return acted
