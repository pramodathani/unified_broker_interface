"""A plan order kept whole as a two-sided quote: one buy and one sell limit kept around a fair price and re-priced as it moves."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)
from unified_broker_interface.utilities.order_engine.utilities.whole_part import (
    WholePart,
)

FAIR_PRICES = (
    'mid',
    'last',
)
QUOTE_SIDES = {
    'bid': 'BUY',
    'ask': 'SELL',
}
SETTINGS = (
    'half_spread_points',
    'skew_ticks',
    'step_ticks',
    'most_inventory',
    'fair_price',
)


class TwoSidedQuotePart(WholePart):
    """A two-sided quote in a plan, with the rules of today's two-sided quote type.

    On every tick the fair price is read, the mid between the best bid and offer by default or the last price with `fair_price: last`, and the bid is kept `half_spread_points` below it and the ask the same distance above. A quote is modified only once its price has moved by at least `step_ticks` ticks. For every order's worth held, both prices move `skew_ticks` ticks against the position, so a long lowers both. A side that fills is quoted again on the next tick. Once the net position reaches `most_inventory`, the side that would add to it is cancelled and not quoted again until the position comes back. The body's quantity is the size of each quote.

    The bid is the part's resting buy and the ask its resting sell, so it needs no memory to tell them apart. It never ends on its own: it keeps quoting until it is stopped, by its join or by the caller, and is done once its orders have finished after that.
    """

    def settings_problems(self):
        """Every problem with the settings, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in SETTINGS:
                problems.append(f'the two_sided_quote preset takes {", ".join(SETTINGS)}, not {name!r}')
        spread = self._positive('half_spread_points')
        if spread is None:
            problems.append(f'a two-sided quote needs half_spread_points as a number above zero, not {self.settings.get("half_spread_points")!r}')
        if self._whole('skew_ticks', 0, 0) is None:
            problems.append(f'skew_ticks must be a whole number of at least 0, not {self.settings.get("skew_ticks")!r}')
        if self._whole('step_ticks', 1, 1) is None:
            problems.append(f'step_ticks must be a whole number of at least 1, not {self.settings.get("step_ticks")!r}')
        if self.settings.get('most_inventory') is None:
            problems.append('a two-sided quote needs most_inventory: a trending market fills one side over and over, and without a cap the position keeps growing at prices that keep getting worse')
        elif self._whole('most_inventory', 0, 1) is None:
            problems.append(f'most_inventory must be a whole number of at least 1, not {self.settings.get("most_inventory")!r}')
        kind = self.settings.get('fair_price', 'mid')
        if kind not in FAIR_PRICES:
            problems.append(f'fair_price must be one of {", ".join(FAIR_PRICES)}, not {kind!r}')
        return problems

    def _positive(self, name):
        """One setting as a number above zero.

        Args:
            name (str): The setting's name.

        Returns:
            decimal.Decimal | None: The number, or None when it is missing or not a number above zero.
        """
        value = self.settings.get(name)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite() or number <= 0:
            return None
        return number

    def _whole(self, name, default, lowest):
        """One setting as a whole number at or above a floor.

        Args:
            name (str): The setting's name.
            default (int): The value when it is not given.
            lowest (int): The smallest value allowed.

        Returns:
            int | None: The number, or None when it is not a whole number at or above `lowest`.
        """
        value = self.settings.get(name, default)
        if isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite() or number != number.to_integral_value() or number < lowest:
            return None
        return int(number)

    def needs_prices(self):
        """Whether this part reads quotes, which it does on every tick.

        Returns:
            bool: True.
        """
        return True

    def moves_on_ticks(self):
        """Whether this part is looked at on every tick, which it is, to keep both quotes in place.

        Returns:
            bool: True.
        """
        return True

    def wanted_prices(self, view, tick_size, net, size):
        """Where the bid and the ask belong now.

        Args:
            view (MarketView): The live quote.
            tick_size (decimal.Decimal | None): The instrument's tick size.
            net (int): The net position the quote's fills have built.
            size (int): The quantity of each quote.

        Returns:
            dict | None: `bid` and `ask` prices (decimal.Decimal), or None when the quote does not carry the fair price.
        """
        if self.settings.get('fair_price', 'mid') == 'mid':
            fair = view.mid()
        else:
            fair = view.last()
        if fair is None or not tick_size:
            return None
        shift = decimal.Decimal(net) / decimal.Decimal(size) * self._whole('skew_ticks', 0, 0) * tick_size
        half_spread = self._positive('half_spread_points')
        bid = view.rounded(fair - half_spread - shift, 'BUY')
        ask = view.rounded(fair + half_spread - shift, 'SELL')
        if bid is None or ask is None or bid <= 0:
            return None
        return {
            'bid': bid,
            'ask': ask,
        }

    def prepared_own_memory(self, plan_order):
        """Checks, when the plan is placed, that the live quote carries the fair price.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: Nothing to remember, so an empty dict.

        Raises:
            RefusedRequestError: With HTTP 503 when the quote does not carry the fair price, or the brokers do not agree on a tick size.
        """
        context = self.context(plan_order)
        order = plan_order.read_order(context.body)
        instrument, quote, _ = context.placement.market_context(context.instrument_id, True, False)
        tick_size = order.agreed_tick_size(instrument.handles)
        if self.wanted_prices(MarketView(quote, tick_size), tick_size, 0, order.quantity) is None:
            raise RefusedRequestError.refusal(
                'a two-sided quote is kept around the fair price, and the live quote does not carry it yet',
                503,
                instrument_id=context.instrument_id,
            )
        return {}

    def live_quote(self, parent, side):
        """The resting order on one side, if there is one.

        Args:
            parent (ParentOrder): The plan order's parent.
            side (str): BUY or SELL.

        Returns:
            OrderLeg | None: The leg.
        """
        for leg in self.own_legs(parent):
            if leg.transaction_type == side and not leg.is_finished():
                return leg
        return None

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Places the bid and the ask around the fair price now.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): Unused, since a quote trades no total.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes.
            now (float | None): Unused.

        Returns:
            list: One `(path, answer, status)` per quote placed.
        """
        del target, now
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} quote is working')
        context = self.context(plan_order)
        size = plan_order.read_order(context.body).quantity
        prices = self.wanted_prices(context.view(quotes), context.tick_size(), self.inventory(plan_order.parent), size)
        if prices is None:
            return []
        placed = []
        for role, side in QUOTE_SIDES.items():
            body, status, _ = self.place_order(plan_order, self.limit_order(plan_order, side, prices[role]), started_at)
            placed.append((self.path, body, status))
        return placed

    def move(self, plan_order, quotes, now):
        """Keeps both quotes where they belong: quotes a filled side again, moves one that is a whole step out, and pulls the side that would pass the cap.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.
            now (float): Unused.

        Returns:
            bool: True when any order was placed, moved or cancelled.
        """
        del now
        record = plan_order.part_record(self.path)
        if record.get('state') != 'working' or self.is_stopped(plan_order):
            return False
        context = self.context(plan_order)
        view = context.view(quotes)
        if view.is_stale():
            return False
        tick_size = context.tick_size()
        net = self.inventory(plan_order.parent)
        size = plan_order.read_order(context.body).quantity
        prices = self.wanted_prices(view, tick_size, net, size)
        if prices is None:
            return False
        at_cap = abs(net) >= self._whole('most_inventory', 0, 1)
        adding = None
        if net > 0:
            adding = 'BUY'
        elif net < 0:
            adding = 'SELL'
        step = tick_size * self._whole('step_ticks', 1, 1)
        acted = False
        for role, side in QUOTE_SIDES.items():
            leg = self.live_quote(plan_order.parent, side)
            if at_cap and side == adding:
                if leg is not None and leg.broker_order_id is not None:
                    if self.cancel_once(plan_order, leg, f'the quote is holding {net}, its whole allowance, so it stops quoting that side'):
                        acted = True
                continue
            if leg is None:
                self.place_order(plan_order, self.limit_order(plan_order, side, prices[role]), None)
                acted = True
                continue
            if leg.broker_order_id is None or leg.price is None:
                continue
            current = decimal.Decimal(str(leg.price))
            if abs(prices[role] - current) < step:
                continue
            if plan_order.reprice_leg(leg, prices[role], None, f'the fair price moved, so the {role} goes to {prices[role]}'):
                acted = True
        return acted

    def settle(self, plan_order):
        """Marks the quote done once it has been stopped and its orders have finished; a filled side is left to the next tick to quote again.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: Nothing is placed while settling, so an empty list.
        """
        if self.is_stopped(plan_order):
            self.finish_when_done(plan_order)
        return []
