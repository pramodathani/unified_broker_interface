"""The execution that splits an order above the exchange's freeze quantity into orders each below it, at one broker."""

import math

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

MOST_SLICES = 20


class FreezeLimitExecution:
    """A plan order's execution that sends an order larger than the chosen broker's freeze quantity as several equal orders, all at once and all to that broker.

    It keeps the rules of today's freeze slicer. The broker is chosen first, through the selector, because each broker publishes its freeze quantity in its own units: for one MCX silver option, brokers with a lot of 30 report 600 and brokers with a lot of 1 report 20, both meaning twenty lots. The order's quantity in that broker's terms is compared with that broker's figure. A broker that publishes none gets the order whole. The slices are cut in whole lots, because each one is placed as an order of its own and an order for part of a lot is refused. More than 20 slices is refused. The broker is kept in the execution's memory so every slice goes to it.
    """

    def needs_prices(self):
        """Whether this execution reads quotes, which it does not.

        Returns:
            bool: False.
        """
        return False

    def paced_by_ticks(self):
        """Whether this execution sends pieces on later ticks, which it does not.

        Returns:
            bool: False.
        """
        return False

    def changes_its_order_to_grow(self):
        """Whether a larger target is met by changing a resting order, which it is not.

        Returns:
            bool: False.
        """
        return False

    def begin(self, plan_order, memory, quotes, now):
        """Readies the execution, which needs nothing until it is asked for pieces.

        Args:
            plan_order (OrderContext): Unused.
            memory (dict): Unused.
            quotes (dict): Unused.
            now (float): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, memory, quotes, now

    def freeze_quantity(self, plan_order, broker_name):
        """The freeze quantity the broker publishes for the order's instrument, in its own units.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            broker_name (str): The broker.

        Returns:
            int | None: The freeze quantity, or None when the broker publishes none.
        """
        attributes = plan_order.placement.broker_attributes(plan_order.instrument_id)
        published = (attributes.get(broker_name) or {}).get('freeze_quantity')
        if published is None:
            return None
        try:
            freeze_quantity = int(float(published))
        except (TypeError, ValueError):
            return None
        if freeze_quantity < 1:
            return None
        return freeze_quantity

    def split(self, total, broker_quantity, freeze_quantity, units_per_lot=None):
        """The slices, each a whole number of lots and as even as whole lots allow.

        The most lots one slice may carry is the freeze quantity's share of the order in lots, so a broker that states its figure in lots or in its own lot size is read the same way as one that states it in units. Each slice is a whole number of lots, because the placement of each slice refuses one that is not; the first slices take one lot more until the remainder is used up. When the lot size is not known, or the order is not a whole number of lots, the slices are as even as whole units allow instead.

        Args:
            total (int): The order's quantity, in units.
            broker_quantity (int | None): The same quantity in the broker's own terms.
            freeze_quantity (int | None): The broker's freeze quantity, or None.
            units_per_lot (int | None): The units in one lot at the broker, or None when it is not known.

        Returns:
            list: One quantity per slice, in units.

        Raises:
            RefusedRequestError: With HTTP 400 when one lot is above the freeze limit, or when it would take more than 20 slices.
        """
        if freeze_quantity is None or not broker_quantity or broker_quantity <= freeze_quantity:
            return [
                total,
            ]
        if units_per_lot is None or total % units_per_lot != 0:
            return self.split_units(total, broker_quantity, freeze_quantity)
        lots = total // units_per_lot
        most_lots = (freeze_quantity * lots) // broker_quantity
        if most_lots < 1:
            raise RefusedRequestError.refusal(
                f'one lot of {units_per_lot} is above the freeze limit of {freeze_quantity}, so the order cannot be split into orders below it',
                400,
            )
        wanted = math.ceil(lots / most_lots)
        self.refuse_too_many(wanted)
        slices = []
        for lots_in_slice in self.shares(lots, wanted):
            slices.append(lots_in_slice * units_per_lot)
        return slices

    def split_units(self, total, broker_quantity, freeze_quantity):
        """The slices as even as whole units allow, for an order whose lot size is not known.

        Args:
            total (int): The order's quantity, in units.
            broker_quantity (int): The same quantity in the broker's own terms.
            freeze_quantity (int): The broker's freeze quantity.

        Returns:
            list: One quantity per slice, in units.

        Raises:
            RefusedRequestError: With HTTP 400 when it would take more than 20 slices.
        """
        wanted = math.ceil(broker_quantity / freeze_quantity)
        self.refuse_too_many(wanted)
        return self.shares(total, wanted)

    def refuse_too_many(self, wanted):
        """Refuses an order that would take more slices than the engine sends at once.

        Args:
            wanted (int): The number of slices the order would take.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when `wanted` is above 20.
        """
        if wanted > MOST_SLICES:
            raise RefusedRequestError.refusal(
                f'this order is {wanted} times the freeze limit, which would take {wanted} orders; the engine sends at most {MOST_SLICES} at once',
                400,
            )

    def shares(self, amount, count):
        """An amount shared into a number of parts as evenly as whole numbers allow, the first parts taking the remainder.

        Args:
            amount (int): The amount to share.
            count (int): The number of parts.

        Returns:
            list: The parts (int), leaving out any that would be zero.
        """
        each = amount // count
        remainder = amount - each * count
        parts = []
        for index in range(count):
            part = each
            if index < remainder:
                part = each + 1
            if part >= 1:
                parts.append(part)
        return parts

    def due_pieces(self, plan_order, memory, total, pieces, quotes, now, sending_side=None):
        """Every slice, the first time it is asked, after choosing the broker they all go to.

        Args:
            plan_order (OrderContext): The order's view of the plan order.
            memory (dict): The execution's memory, given `broker` and `freeze_quantity`.
            total (int): The order's quantity.
            pieces (list): The broker orders sent so far.
            quotes (dict): Unused.
            now (float): Unused.
            sending_side (str | None): BUY or SELL, the side the order is sent on.

        Returns:
            list: One quantity per slice, or nothing once they are sent.

        Raises:
            RefusedRequestError: When the broker cannot be chosen or the order would take more than 20 slices.
        """
        del quotes, now
        if not self.will_send_more(memory, total, pieces):
            return []
        body = dict(plan_order.body)
        body['quantity'] = total
        if sending_side is not None:
            body['transaction_type'] = sending_side
        broker_name = plan_order.chosen_broker() or body.get('broker')
        prepared = plan_order.placement.prepare(plan_order.read_order(body), plan_order.instrument_id, broker_name)
        freeze_quantity = self.freeze_quantity(plan_order, prepared.broker_name)
        slices = self.split(total, prepared.broker_quantity, freeze_quantity, prepared.units_per_lot)
        memory['broker'] = prepared.broker_name
        memory['freeze_quantity'] = freeze_quantity
        return slices

    def will_send_more(self, memory, remaining, pieces):
        """Whether the slices are still to be sent, which they are only before any has been.

        Args:
            memory (dict): Unused.
            remaining (int): Unused.
            pieces (list): The broker orders sent so far.

        Returns:
            bool: True before the slices are sent.
        """
        del memory, remaining
        return not pieces

    def described(self):
        """This execution as a dry run shows it.

        Returns:
            str: `freeze_limit`.
        """
        return 'freeze_limit'
