"""Two stop entries either side of a range, where the first to fill cancels the other."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.bracket import Bracket
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
)


class TwoSidedBreakout(Bracket):
    """A buy stop above a range and a sell stop below it, whichever fires first.

    Somebody who thinks a range is about to break but does not know which way puts an order on both sides. Both entries are native stop orders, so they fire at exchange speed without the engine being involved at all, which is the property the Atlas keeps returning to: a native order goes on working while your process is down.

    What the engine adds is what happens next. **The first fill cancels the other side**, because a spike through both sides of a range is exactly what a whipsaw does, and being long and short at once is not a position anybody asked for. Cancelling is the right verb here rather than reducing: the other entry is not a tranche of the same position, it is the opposite trade.

    Once an entry has filled, the exits are armed on the side that filled. They are given as distances from the fill, `stop_distance` with `stop_limit_offset` and `target_distance`, because one absolute price cannot suit a break either way: after a break downwards a target above the range would buy straight back. A long's stop sits below its fill and its target above; a short's the other way round.

    It cannot make the double fill impossible. A spike through both triggers in the same tick fills both before any cancel can leave, and the account is then flat having paid the spread twice. The engine records that and reports it; only the exchange could prevent it, and it offers no such order.
    """

    SYNTHETIC_TYPE = 'two_sided_breakout'

    def run(self, intent, started_at):
        """Places both stop entries. Whichever fires cancels the other.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: For an order answered without calling a broker.
        """
        order = self.read_order(self.parent.body)
        entries = self.entry_orders(order)

        if order.dry_run:
            prepared = self.placement.prepare(
                entries[0][1],
                self.parent.instrument_id,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.remember_tick_size(order)
        self.record_received()
        self.save()

        answers = []
        broker_name = None
        for role, entry_order in entries:
            body, status, _ = self.place_leg(
                role,
                entry_order,
                started_at,
                broker_name,
            )
            if broker_name is None:
                broker_name = body.get('broker')
            answers.append((role, body, status))

        outcomes = [body.get('outcome') for _, body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'working'
        else:
            state = 'rejected'
        self.record_state(state, None)
        self.save()
        return self.answer(answers, broker_name)

    def entry_orders(self, order):
        """The two stop entries, above and below the range.

        Args:
            order (PlaceOrderRequest): The validated order, whose quantity both entries take.

        Returns:
            list: `(role, PlaceOrderRequest)` for the buy side then the sell side.

        Raises:
            RefusedRequestError: With HTTP 400 when either side's prices are missing, or the exits are not given as distances.
        """
        exits = ExitLegs()
        parameters = self.parent.parameters
        self.read_exit_distances()
        buy_trigger = exits.price(parameters, 'buy_trigger')
        buy_limit = exits.price(parameters, 'buy_limit')
        sell_trigger = exits.price(parameters, 'sell_trigger')
        sell_limit = exits.price(parameters, 'sell_limit')
        if None in (buy_trigger, buy_limit, sell_trigger, sell_limit):
            raise RefusedRequestError.refusal(
                'a two_sided_breakout needs buy_trigger, buy_limit, '
                'sell_trigger and sell_limit: both sides are stop-limit '
                'orders and each needs its own two prices',
                400,
            )
        if sell_trigger >= buy_trigger:
            raise RefusedRequestError.refusal(
                'sell_trigger must be below buy_trigger; they are the two '
                'sides of a range and a range has a top and a bottom',
                400,
            )
        return [
            (
                'entry',
                exits.exit_order(
                    order,
                    'BUY',
                    order.quantity,
                    'SL',
                    buy_limit,
                    buy_trigger,
                ),
            ),
            (
                'entry',
                exits.exit_order(
                    order,
                    'SELL',
                    order.quantity,
                    'SL',
                    sell_limit,
                    sell_trigger,
                ),
            ),
        ]

    def on_entry_update(self, leg, changes):
        """Cancels the other side, then protects whatever filled.

        Args:
            leg (OrderLeg): The entry that changed.
            changes (dict): What the update changed.

        Returns:
            None: This method returns nothing.
        """
        filled = leg.filled_quantity or 0
        if filled < 1:
            if changes.get('leg_state') in ('rejected', 'cancelled'):
                self.finish_if_done()
            return
        self.cancel_other_side(leg)
        super().on_entry_update(leg, changes)

    def cancel_other_side(self, filled_entry):
        """Cancels the entry that did not fire.

        Args:
            filled_entry (OrderLeg): The entry that filled.

        Returns:
            None: This method returns nothing.
        """
        for leg in self.parent.legs:
            if leg.role != 'entry' or leg.leg_id == filled_entry.leg_id:
                continue
            if leg.is_finished() or not leg.is_live():
                continue
            self.cancel_leg(
                leg,
                'the other side of the range broke first, so this entry is '
                'being taken off rather than left to whipsaw into it',
            )

    def arm_exits(self, entry, filled):
        """Places the stop and the target on the side that actually filled.

        The caller's `transaction_type` says nothing useful here, because the trade could have gone either way. The exits are built against the entry that filled instead.

        Args:
            entry (OrderLeg): The entry leg that filled.
            filled (int): How much it filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        order = self.read_order(self.parent.body)
        taken = order.with_quantities(filled, 0)
        taken.transaction_type = entry.transaction_type or order.transaction_type
        legs = ExitLegs().build(taken, self.exit_prices(entry, taken.transaction_type), filled)
        for role, exit_order in legs:
            self.place_leg(role, exit_order, None, entry.broker)
        self.record_state('protecting', None)
        self.save()

    def read_exit_distances(self):
        """The exits' distances from the fill, checked.

        Returns:
            tuple: `stop_distance`, `stop_limit_offset` and `target_distance` (decimal.Decimal or None each).

        Raises:
            RefusedRequestError: With HTTP 400 when the exits are given as absolute prices, neither exit is given, a stop has no `stop_limit_offset`, or a distance is not above zero.
        """
        parameters = self.parent.parameters
        absolute = []
        for name in ('stop_price', 'stop_limit_price', 'target_price'):
            if parameters.get(name) is not None:
                absolute.append(name)
        if absolute:
            raise RefusedRequestError.refusal(
                'a two_sided_breakout takes its exits as distances from the fill, stop_distance with stop_limit_offset and target_distance, because one absolute price cannot suit a break either way; '
                f'it was given {", ".join(absolute)}',
                400,
            )
        exits = ExitLegs()
        stop_distance = exits.price(parameters, 'stop_distance')
        stop_limit_offset = exits.price(parameters, 'stop_limit_offset')
        target_distance = exits.price(parameters, 'target_distance')
        if stop_distance is None and target_distance is None:
            raise RefusedRequestError.refusal(
                'a two_sided_breakout needs a stop_distance, a target_distance, or both',
                400,
            )
        if stop_distance is not None and stop_limit_offset is None:
            raise RefusedRequestError.refusal(
                'a stop needs stop_limit_offset as well as stop_distance: a stop-limit whose limit sits at its trigger will not fill when the price runs through it',
                400,
            )
        return stop_distance, stop_limit_offset, target_distance

    def exit_prices(self, entry, opened_side):
        """The exits' absolute prices for the side that filled, worked out from the entry's fill.

        The fill is the entry's average price, or its trigger when the broker has not said; each price is rounded to the nearest tick.

        Args:
            entry (OrderLeg): The entry leg that filled.
            opened_side (str): BUY or SELL, the side the position was opened on.

        Returns:
            dict: `stop_price` and `stop_limit_price`, `target_price`, or all three, as `ExitLegs.build` reads them.
        """
        stop_distance, stop_limit_offset, target_distance = self.read_exit_distances()
        filled_at = decimal.Decimal(str(entry.average_price or entry.trigger_price or entry.price))
        towards_profit = decimal.Decimal(1) if opened_side == 'BUY' else decimal.Decimal(-1)
        prices = {}
        if stop_distance is not None:
            stop = self.on_tick(filled_at - towards_profit * stop_distance)
            prices['stop_price'] = format(stop, 'f')
            prices['stop_limit_price'] = format(self.on_tick(stop - towards_profit * stop_limit_offset), 'f')
        if target_distance is not None:
            prices['target_price'] = format(self.on_tick(filled_at + towards_profit * target_distance), 'f')
        return prices

    def on_tick(self, price):
        """A price rounded to the nearest tick, or left as it is when the tick size is not known.

        Args:
            price (decimal.Decimal): The price.

        Returns:
            decimal.Decimal: The rounded price.
        """
        tick_size = self.tick_size()
        if not tick_size:
            return price
        ticks = (price / tick_size).to_integral_value(rounding=decimal.ROUND_HALF_UP)
        return (ticks * tick_size).quantize(tick_size)

    def answer(self, answers, broker_name):
        """The one answer the waiting API worker gets for a two-sided breakout.

        Args:
            answers (list): One `(role, body, status)` per entry.
            broker_name (str | None): The broker both entries went to.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        bodies = [body for _, body, _ in answers]
        outcomes = [body.get('outcome') for body in bodies]
        outcome, status = self.combined_answer(
            outcomes,
            [status for _, _, status in answers],
        )
        return {
            'broker': broker_name,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': outcome,
            'sides': [
                {
                    'transaction_type': (
                        'BUY' if position == 0 else 'SELL'
                    ),
                    'order_id': body.get('order_id'),
                    'outcome': body.get('outcome'),
                }
                for position, (_, body, _) in enumerate(answers)
            ],
            'skipped': bodies[0].get('skipped') if bodies else [],
            'timing_ms': bodies[0].get('timing_ms') if bodies else {},
        }, status
