"""A plan order kept whole as a strategy stop's exits: every leg a basket filled marked to the market, and all of them closed once the total crosses a line."""

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

DEFAULT_BUFFER_TICKS = 2
SETTINGS = (
    'loss_limit',
    'profit_target',
)


class StrategyStopExitsPart(WholePart):
    """The exits of a strategy stop in a plan, with the rules of today's strategy stop type; the `strategy_stop` preset puts them under a Then join after a basket.

    On every tick each broker order the first plan filled is marked to its instrument's last price against what it filled at, and the marks are added up. Only a total in which every filled order could be marked is acted on, and a quote marked stale cannot mark one. When it is at or below `loss_limit`, which is below zero, or at or above `profit_target`, which is above zero, the first plan's orders still resting are cancelled and every filled order is closed, shorts before the longs that hedge them, each as a limit two ticks past its touch for what it filled, in its own product, at the broker that holds it. The levels act once; after that, whatever the first plan fills before its cancels land is closed the same way, and the exits are done only once nothing of the first plan rests and every close has finished. A close the broker rejects is not sent again, and its join then ends the parent `failed`.

    The instruments it marks are the first plan's, which the reader hands it, so the plan watches their quotes; their tick sizes are worked out when the plan is placed and kept in its memory. It must be a Then join's child.

    Attributes:
        NEEDS_THEN (bool): True, since it closes what a Then join's first plan filled.
    """

    NEEDS_THEN = True

    def _number(self, name):
        """One of the levels, as a number.

        Args:
            name (str): The setting's name.

        Returns:
            decimal.Decimal | None: The value, or None when it is not given or not a number.
        """
        value = self.settings.get(name)
        if value is None or isinstance(value, bool):
            return None
        try:
            number = decimal.Decimal(str(value))
        except (decimal.InvalidOperation, TypeError, ValueError):
            return None
        if not number.is_finite():
            return None
        return number

    def settings_problems(self):
        """Every problem with the levels, in today's words.

        Returns:
            list: One message (str) per problem.
        """
        problems = []
        for name in self.settings:
            if name not in SETTINGS:
                problems.append(f'the strategy_stop_exits preset takes loss_limit and profit_target, not {name!r}')
        for name in SETTINGS:
            if name in self.settings and self._number(name) is None:
                problems.append(f'{name} must be a number, not {self.settings.get(name)!r}')
        loss = self._number('loss_limit')
        profit = self._number('profit_target')
        if 'loss_limit' not in self.settings and 'profit_target' not in self.settings:
            problems.append('a strategy stop needs loss_limit, profit_target, or both')
        if loss is not None and loss >= 0:
            problems.append(f'loss_limit is a loss, so it must be below zero, not {loss}')
        if profit is not None and profit <= 0:
            problems.append(f'profit_target must be above zero, not {profit}')
        return problems

    def instruments(self):
        """The instruments the first plan trades, whose quotes it marks.

        Returns:
            list: The instrument ids.
        """
        watched = []
        for instrument_id in self.opened_instruments:
            if instrument_id is not None and instrument_id not in watched:
                watched.append(instrument_id)
        return watched

    def needs_prices(self):
        """Whether this part reads quotes, which it does to mark the strategy.

        Returns:
            bool: True.
        """
        return True

    def moves_on_ticks(self):
        """Whether this part is looked at on every tick, which it is, to mark the strategy.

        Returns:
            bool: True.
        """
        return True

    def prepared_own_memory(self, plan_order):
        """Works out, when the plan is placed, the tick size of every instrument it marks.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: `tick_sizes`, by instrument id.

        Raises:
            RefusedRequestError: With HTTP 503 when the brokers do not agree on a tick size for one of them.
        """
        order = plan_order.read_order(self.context(plan_order).body)
        wanted = [
            plan_order.parent.instrument_id,
        ]
        for instrument_id in self.instruments():
            if instrument_id not in wanted:
                wanted.append(instrument_id)
        tick_sizes = {}
        for instrument_id in wanted:
            instrument, _, _ = plan_order.placement.market_context(instrument_id, False, False)
            tick_size = order.agreed_tick_size(instrument.handles)
            if tick_size is None:
                raise RefusedRequestError.refusal(
                    'a strategy stop marks every leg from the live quote, which needs a tick size the brokers agree on, and there is none for this instrument',
                    503,
                    instrument_id=instrument_id,
                )
            tick_sizes[instrument_id] = str(tick_size)
        return {
            'tick_sizes': tick_sizes,
        }

    def view(self, plan_order, quotes, instrument_id):
        """One instrument's market, with the tick size kept when the plan was placed.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes, by instrument id.
            instrument_id (str): The instrument.

        Returns:
            MarketView: The view.
        """
        tick_size = (self.own_memory(plan_order).get('tick_sizes') or {}).get(instrument_id)
        if tick_size is not None:
            tick_size = decimal.Decimal(tick_size)
        return MarketView(quotes.get(instrument_id), tick_size)

    def filled_legs(self, plan_order):
        """The first plan's broker orders that have filled anything.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: The legs.
        """
        found = []
        for leg in plan_order.parent.legs:
            if leg.role in self.opened_by and leg.filled_quantity:
                found.append(leg)
        return found

    def leg_profit(self, plan_order, leg, quotes):
        """What one filled order is worth now against what it filled at.

        Args:
            plan_order (PlanOrder): The plan order.
            leg (OrderLeg): The order.
            quotes (dict): The quotes the tick carried.

        Returns:
            decimal.Decimal | None: The profit in rupees, or None when it cannot be marked, including from a quote marked stale.
        """
        entered_at = leg.average_price or leg.price
        instrument_id = leg.instrument_id or plan_order.parent.instrument_id
        view = self.view(plan_order, quotes, instrument_id)
        if view.is_stale():
            return None
        now = view.last()
        if not entered_at or now is None:
            return None
        moved = now - decimal.Decimal(str(entered_at))
        if leg.transaction_type == 'SELL':
            moved = -moved
        return moved * leg.filled_quantity

    def start(self, plan_order, target, started_at, quotes, now=None):
        """Starts marking the strategy once the first plan has filled something, placing nothing.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int): How much the first plan has filled.
            started_at (float | None): Unused.
            quotes (dict): Unused.
            now (float | None): Unused.

        Returns:
            list: Nothing is placed, so an empty list.
        """
        del target, started_at, quotes, now
        record = plan_order.part_record(self.path)
        record['state'] = 'working'
        plan_order.set_part_record(self.path, record, f'the plan\'s {self.path} part marks the strategy against loss_limit {self.settings.get("loss_limit")} and profit_target {self.settings.get("profit_target")}')
        return []

    def set_target(self, plan_order, target):
        """Follows the first plan's fills, which it reads from the legs when it marks, so nothing changes.

        Args:
            plan_order (PlanOrder): Unused.
            target (int): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, target

    def exit_order(self, plan_order, leg, quotes, quantity=None):
        """The order that closes one filled order, priced two ticks past its touch.

        Args:
            plan_order (PlanOrder): The plan order.
            leg (OrderLeg): The order to close.
            quotes (dict): The quotes the tick carried.
            quantity (int | None): How much to close, or None for all it filled.

        Returns:
            PlaceOrderRequest | None: The order, or None when the book gives nothing to price against.
        """
        side = 'SELL' if leg.transaction_type == 'BUY' else 'BUY'
        view = self.view(plan_order, quotes, leg.instrument_id or plan_order.parent.instrument_id)
        touch = view.opposite_touch(side)
        if touch is None:
            touch = view.last()
        if touch is None:
            return None
        price = view.rounded(view.moved(touch, DEFAULT_BUFFER_TICKS, side, True), side)
        if price is None or price <= 0:
            return None
        body = dict(plan_order.parent.body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('tag', None)
        body['order_type'] = 'LIMIT'
        body['quantity'] = leg.filled_quantity if quantity is None else quantity
        body['transaction_type'] = side
        body['product'] = leg.product
        body['price'] = str(price)
        return plan_order.concrete_order(plan_order.read_order(body))

    def move(self, plan_order, quotes, now):
        """Closes every filled order, shorts first, once the total crosses a level.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes the tick carried.
            now (float): The Unix time of the tick.

        Returns:
            bool: True when the strategy was closed on this tick.
        """
        memory = self.own_memory(plan_order)
        if plan_order.part_record(self.path).get('state') != 'working' or self.is_stopped(plan_order) or memory.get('closed_at') is not None:
            return False
        legs = self.filled_legs(plan_order)
        total = decimal.Decimal('0')
        for leg in legs:
            profit = self.leg_profit(plan_order, leg, quotes)
            if profit is None:
                return False
            total = total + profit
        loss = self._number('loss_limit')
        target = self._number('profit_target')
        if loss is not None and total <= loss:
            reason = f'the strategy is down {total}, past its limit of {loss}'
        elif target is not None and total >= target:
            reason = f'the strategy is up {total}, past its target of {target}'
        else:
            return False
        memory['closed_at'] = now
        memory['closed_at_profit'] = str(total)
        self.remember(plan_order, memory, reason)
        self.cancel_first_plan(plan_order)
        self.close_open(plan_order, quotes)
        return True

    def cancel_first_plan(self, plan_order):
        """Cancels whatever of the first plan is still resting, so it fills nothing more once the strategy is closed.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            None: This method returns nothing.
        """
        for leg in plan_order.parent.legs:
            if leg.role in self.opened_by and not leg.is_finished() and leg.broker_order_id:
                self.cancel_once(plan_order, leg, 'the strategy stop closed the strategy')

    def leg_key(self, plan_order, leg, side):
        """What a close is matched to the order it closes by: the instrument, broker, product and side of the position.

        Args:
            plan_order (PlanOrder): The plan order.
            leg (OrderLeg): A first plan order or a close.
            side (str): The side of the position, BUY for a long.

        Returns:
            tuple: The key.
        """
        return (leg.instrument_id or plan_order.parent.instrument_id, leg.broker, leg.product, side)

    def still_open(self, plan_order):
        """How much of each filled first plan order no close has been sent for yet.

        It is worked out from the legs alone, so a restart sends nothing twice: every close counts its whole quantity, whatever became of it, so a close the broker rejected is not sent again.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: Pairs of a first plan order (OrderLeg) and the quantity (int) still to close for it.
        """
        sent = {}
        for leg in self.own_legs(plan_order.parent):
            side = 'SELL' if leg.transaction_type == 'BUY' else 'BUY'
            key = self.leg_key(plan_order, leg, side)
            sent[key] = sent.get(key, 0) + (leg.quantity or 0)
        found = []
        for leg in self.filled_legs(plan_order):
            key = self.leg_key(plan_order, leg, leg.transaction_type)
            covered = min(sent.get(key, 0), leg.filled_quantity)
            sent[key] = sent.get(key, 0) - covered
            if leg.filled_quantity > covered:
                found.append((leg, leg.filled_quantity - covered))
        return found

    def close_open(self, plan_order, quotes):
        """Closes what no close has been sent for yet, shorts before longs.

        Args:
            plan_order (PlanOrder): The plan order.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per close placed.
        """
        shorts = []
        longs = []
        for leg, quantity in self.still_open(plan_order):
            if leg.transaction_type == 'SELL':
                shorts.append((leg, quantity))
            else:
                longs.append((leg, quantity))
        placed = []
        for leg, quantity in shorts + longs:
            order = self.exit_order(plan_order, leg, quotes, quantity)
            if order is None:
                continue
            body, status, _ = plan_order.place_leg(self.path, order, None, leg.broker, leg.instrument_id or plan_order.parent.instrument_id)
            placed.append((self.path, body, status))
        return placed

    def first_plan_rests(self, plan_order):
        """Whether any order of the first plan may still fill.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            bool: True while one has not finished.
        """
        for leg in plan_order.parent.legs:
            if leg.role in self.opened_by and not leg.is_finished():
                return True
        return False

    def settle(self, plan_order):
        """Closes what the first plan filled after the strategy was closed, and marks the exits done once nothing of the first plan rests and every close has finished.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            list: One `(path, answer, status)` per close placed while settling.
        """
        if plan_order.part_record(self.path).get('state') != 'working':
            return []
        placed = []
        closed = self.own_memory(plan_order).get('closed_at') is not None
        if closed and not self.is_stopped(plan_order) and self.still_open(plan_order):
            try:
                quotes = plan_order.quotes_now()
            except RefusedRequestError as refusal:
                plan_order.logger.warning(f'Parent {plan_order.parent.parent_order_id} could not read the quotes to close a late fill: {refusal.body.get("error")}')
                quotes = None
            if quotes is not None:
                placed = self.close_open(plan_order, quotes)
        if self.is_stopped(plan_order) or (closed and not self.first_plan_rests(plan_order)):
            self.finish_when_done(plan_order)
        return placed
