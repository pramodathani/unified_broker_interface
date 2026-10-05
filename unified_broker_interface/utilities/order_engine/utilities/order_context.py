"""One order of a plan, as its pricing, execution and trigger see the plan: on that order's own instrument and body."""

import decimal

from unified_broker_interface.utilities.order_engine.utilities.market_view import (
    MarketView,
)


class OrderContext:
    """The plan order as one of its orders sees it, which may trade an instrument other than the parent's.

    A plan's orders can each name their own instrument, quantity and side, as a basket's do. Pricing, execution and triggers ask the plan order for a market view, a tick size, the body and the instrument; this answers each of those for the order's own instrument and body, and hands every other request on to the plan order with the instrument added where a broker order is placed. When the order trades the parent's own instrument, every request goes to the plan order unchanged.

    Attributes:
        plan_order (PlanOrder): The plan order.
        instrument_id (str): The instrument this order trades.
        body (dict): The caller's body with this order's own values written over it.
        parent (ParentOrder): The plan order's parent.
    """

    def __init__(self, plan_order, instrument_id, body):
        """Builds the context.

        Args:
            plan_order (PlanOrder): The plan order.
            instrument_id (str): The instrument this order trades.
            body (dict): The body this order starts from.

        Returns:
            None: This method returns nothing.
        """
        self.plan_order = plan_order
        self.instrument_id = instrument_id
        self.body = body
        self.parent = plan_order.parent

    @property
    def placement(self):
        """The plan order's placement, which reads the catalogue."""
        return self.plan_order.placement

    def is_parents_instrument(self, instrument_id=None):
        """Whether an instrument is the parent's own.

        Args:
            instrument_id (str | None): The instrument, or None for this order's.

        Returns:
            bool: True when it is.
        """
        wanted = instrument_id or self.instrument_id
        return wanted == self.parent.instrument_id

    def tick_size(self, instrument_id=None):
        """The tick size of this order's instrument, or of another one.

        Args:
            instrument_id (str | None): The instrument, or None for this order's.

        Returns:
            decimal.Decimal | None: The tick size, or None when it is not known.
        """
        if self.is_parents_instrument(instrument_id):
            return self.plan_order.tick_size()
        wanted = instrument_id or self.instrument_id
        text = (self.parent.parameters.get('tick_sizes') or {}).get(wanted)
        if not text:
            return self.plan_order.tick_size()
        return decimal.Decimal(str(text))

    def view(self, quotes, instrument_id=None):
        """The market of this order's instrument, or of another one, as its quote and tick size show it.

        Args:
            quotes (dict): The quotes, by instrument id.
            instrument_id (str | None): The instrument, or None for this order's.

        Returns:
            MarketView: The view.
        """
        if self.is_parents_instrument(instrument_id):
            return self.plan_order.view(quotes, instrument_id)
        wanted = instrument_id or self.instrument_id
        return MarketView(quotes.get(wanted), self.tick_size(wanted))

    def trading_segment(self):
        """The exchange-prefixed segment of this order's instrument, whose calendar its times follow.

        Returns:
            str: The segment.
        """
        if self.is_parents_instrument():
            return self.plan_order.trading_segment()
        instrument, _, _ = self.placement.market_context(self.instrument_id, False, False)
        return instrument.segment

    def place_leg(self, role, order, started_at, broker_name=None, leg_group=None):
        """Places one broker order on this order's instrument.

        Args:
            role (str): The leg's role.
            order (PlaceOrderRequest): The order.
            started_at (float | None): When the engine took the intent, or None.
            broker_name (str | None): The broker, or None for the selector to choose.
            leg_group (OrderLegs | None): The group whose margin the selector checks together, or None.

        Returns:
            tuple: The answer (dict), its HTTP status (int) and the leg's id (str).
        """
        if self.is_parents_instrument() and leg_group is None:
            return self.plan_order.place_leg(role, order, started_at, broker_name)
        return self.plan_order.place_leg(role, order, started_at, broker_name, self.instrument_id, leg_group)

    def cancel_leg(self, leg, reason):
        """Cancels a broker order, through the plan order.

        Args:
            leg (OrderLeg): The broker order.
            reason (str): Why.

        Returns:
            bool: True when the broker accepted the cancel.
        """
        return self.plan_order.cancel_leg(leg, reason)

    def reduce_leg(self, leg, quantity, reason):
        """Reduces a broker order, through the plan order.

        Args:
            leg (OrderLeg): The broker order.
            quantity (int): Its new total quantity.
            reason (str): Why.

        Returns:
            bool: True when the broker accepted the change.
        """
        return self.plan_order.reduce_leg(leg, quantity, reason)

    def read_order(self, body):
        """Validates a body as an order, through the plan order.

        Args:
            body (dict): The body.

        Returns:
            PlaceOrderRequest: The order.
        """
        return self.plan_order.read_order(body)

    def chosen_broker(self):
        """The broker the plan's orders go to, once one has been chosen.

        Returns:
            str | None: The broker, or None before any order was placed.
        """
        return self.plan_order.chosen_broker()

    def lot_size(self):
        """The order's instrument's lot at the broker the plan's orders go to, which every slice must be a whole number of.

        Any execution that cuts an order into pieces needs it: a piece that is not a whole number of lots is refused when it is sent.

        Returns:
            int: The lot, at least one: the chosen broker's, or before any broker is chosen the largest any broker lists.
        """
        instrument, _, _ = self.placement.market_context(self.instrument_id, False, False)
        handles = instrument.handles or {}
        broker_name = self.chosen_broker()
        if broker_name is not None:
            chosen = {
                broker_name: handles.get(broker_name) or {},
            }
            handles = chosen
        largest = 1
        for handle in handles.values():
            try:
                size = int(float(handle.get('lot_size') or 1))
            except (TypeError, ValueError):
                size = 1
            largest = max(largest, size)
        return largest
