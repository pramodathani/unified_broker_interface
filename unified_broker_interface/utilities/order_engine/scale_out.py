"""A position taken off in tranches, with one stop that shrinks behind them."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.bracket import Bracket
from unified_broker_interface.utilities.order_engine.utilities.exit_legs import (
    ExitLegs,
    OPPOSITE_SIDES,
)


class ScaleOut(Bracket):
    """A bracket with several targets, each taking part of the position off.

    A trader who is right is right by degrees. Taking a third off at the first target, a third at the second and leaving a third to run is a different trade from taking all of it at one price, and it is not expressible as a single order anywhere.

    It is a bracket with the target replaced by several, so it inherits the entry, the arming on first partial fill and the cancelling of a working entry when an exit starts filling. What it changes is what a fill means:

    **A target filling reduces only the stop, not the other targets.** That is the one place the plain OCO rule would be wrong here. The targets are tranches of the same position, sized to add up to it; reducing each by what another filled would shrink the position's cover to nothing after the first fill. The stop, which covers the whole remaining position, is the only leg that has to follow.

    **After `breakeven_after` targets have filled, the stop moves to the entry's average price.** A trade that has reached its first target has paid for itself, and a stop still sitting below the entry is risking money the position has already made. The move is a price change on the resting order, so it keeps whatever queue position a broker gives it.
    """

    SYNTHETIC_TYPE = 'scale_out'

    def target_prices(self):
        """The prices the targets rest at, cheapest first for a long.

        Returns:
            list: The prices, as `decimal.Decimal`.

        Raises:
            RefusedRequestError: With HTTP 400 when `target_prices` is missing, too short or not prices.
        """
        listed = self.parent.parameters.get('target_prices')
        if not isinstance(listed, list) or len(listed) < 2:
            raise RefusedRequestError.refusal(
                'a scale_out needs target_prices, a list of at least two '
                'prices to take the position off at',
                400,
            )
        exits = ExitLegs()
        prices = []
        for position, value in enumerate(listed):
            field_name = f'target_prices[{position}]'
            prices.append(exits.price(
                {
                    field_name: value,
                },
                field_name,
            ))
        return prices

    def arm_exits(self, entry, filled):
        """Places one stop for the whole filled quantity and the targets that share it.

        Args:
            entry (OrderLeg): The entry leg.
            filled (int): How much the entry has filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        order = self.read_order(self.parent.body)
        exits = ExitLegs()
        prices = self.target_prices()
        if filled < len(prices):
            # Fewer units than targets: protect what there is with the stop and take it all off at
            # the last target rather than placing orders for nothing.
            prices = prices[-1:]

        stop_price = exits.price(self.parent.parameters, 'stop_price')
        stop_limit_price = exits.price(
            self.parent.parameters,
            'stop_limit_price',
        )
        if stop_price is None or stop_limit_price is None:
            raise RefusedRequestError.refusal(
                'a scale_out needs stop_price and stop_limit_price: the stop '
                'is what covers whatever has not been taken off yet',
                400,
            )
        exit_side = OPPOSITE_SIDES[order.transaction_type]
        self.place_leg(
            'stop',
            exits.exit_order(
                order,
                exit_side,
                filled,
                'SL',
                stop_limit_price,
                stop_price,
            ),
            None,
            entry.broker,
        )
        for quantity, price in zip(self.tranches(filled, len(prices)), prices):
            self.place_leg(
                'target',
                exits.exit_order(
                    order,
                    exit_side,
                    quantity,
                    'LIMIT',
                    price,
                    None,
                ),
                None,
                entry.broker,
            )
        self.record_state('protecting', None)
        self.save()

    def tranches(self, filled, count):
        """How much each target takes, as evenly as whole units allow.

        Args:
            filled (int): The whole position, in the broker's own terms.
            count (int): How many targets share it.

        Returns:
            list: One quantity per target.
        """
        each = filled // count
        remainder = filled - each * count
        quantities = []
        for index in range(count):
            quantities.append(each + (1 if index < remainder else 0))
        return quantities

    def grow_exits(self, exits, filled):
        """Brings the stop up to what the entry has now filled, and leaves the targets alone.

        The targets were sized as tranches of the position the stop covers. Growing them each time the entry fills further would make them add up to more than the position.

        Args:
            exits (list): The exit legs.
            filled (int): How much the entry has filled, in the broker's own terms.

        Returns:
            None: This method returns nothing.
        """
        for leg in exits:
            if leg.role != 'stop' or leg.is_finished():
                continue
            wanted = filled - (leg.filled_quantity or 0)
            if wanted == leg.quantity or wanted < 1:
                continue
            self.reduce_leg(
                leg,
                wanted,
                f'the entry has now filled {filled}, so the stop covers it',
            )
        self.save()

    def rebalance(self, filled_leg):
        """Brings the stop down by what a target took off, leaving the other targets as they are.

        Args:
            filled_leg (OrderLeg): The leg that filled.

        Returns:
            None: This method returns nothing.
        """
        if filled_leg.role == 'stop':
            super().rebalance(filled_leg)
            return
        for leg in self.parent.legs:
            if leg.role != 'stop' or leg.is_finished():
                continue
            remaining = (leg.quantity or 0) - (filled_leg.filled_quantity or 0)
            if remaining == leg.quantity:
                continue
            self.reduce_leg(
                leg,
                remaining,
                f'a target took off {filled_leg.filled_quantity}, so the stop '
                'covers what is left',
            )
        self.move_stop_to_breakeven()
        self.save()

    def move_stop_to_breakeven(self):
        """Moves the stop to the entry's average price once enough targets have filled.

        Returns:
            None: This method returns nothing.
        """
        wanted = self.parent.parameters.get('breakeven_after')
        if wanted is None:
            wanted = 1
        try:
            wanted = int(wanted)
        except (TypeError, ValueError):
            return
        if wanted < 1 or self.filled_targets() < wanted:
            return
        if self.parent.parameters.get('stop_at_breakeven'):
            return
        entry = self.entry_leg()
        if entry is None or not entry.average_price:
            return
        stop = self.live_stop()
        if stop is None:
            return
        moved = self.reprice_leg(
            stop,
            entry.average_price,
            entry.average_price,
            f'{wanted} target(s) have filled, so the stop moves to the '
            'entry price and the trade can no longer lose',
        )
        if moved:
            self.parent.parameters = dict(self.parent.parameters)
            self.parent.parameters['stop_at_breakeven'] = True

    def filled_targets(self):
        """How many targets have filled anything.

        Returns:
            int: The count.
        """
        count = 0
        for leg in self.parent.legs:
            if leg.role == 'target' and (leg.filled_quantity or 0) > 0:
                count = count + 1
        return count

    def entry_leg(self):
        """This order's entry, or None.

        Returns:
            OrderLeg | None: The entry leg.
        """
        for leg in self.parent.legs:
            if leg.role == 'entry':
                return leg
        return None

    def live_stop(self):
        """The stop, while it can still fill.

        Returns:
            OrderLeg | None: The stop leg.
        """
        for leg in self.parent.legs:
            if leg.role == 'stop' and not leg.is_finished():
                return leg
        return None
