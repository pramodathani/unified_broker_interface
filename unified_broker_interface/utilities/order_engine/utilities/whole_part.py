"""What every plan order kept whole shares: settings of its own, memory kept in its part record, and broker orders placed by its own rules."""

from unified_broker_interface.utilities.order_engine.utilities.fixed_pricing import (
    FixedPricing,
)
from unified_broker_interface.utilities.order_engine.utilities.order_part import (
    OrderPart,
)


class WholePart(OrderPart):
    """The base of a plan order that one of the kept-whole types runs, such as a grid.

    These types keep many broker orders going by rules no join expresses, so each is ported whole as a single part. It sits in a plan like any order: a join starts it, settles it and asks whether it is done. What it places carries its path as the leg's role, like any order's, so its broker orders are told apart by their leg ids, which it remembers in its part record. A subclass reads its own settings, checks them in `settings_problems`, and does its work in `start`, `settle` and, when it follows prices, `move`.

    Attributes:
        name (str): The preset that names the type, such as `grid`.
        settings (dict): The preset's settings, as the caller wrote them.
    """

    def __init__(self, path, name, settings, keeps_tag=True, overrides=None):
        """Builds the part from the preset the plan reader found.

        Args:
            path (str): The part's path in the plan.
            name (str): The preset's name.
            settings (dict): The preset's settings.
            keeps_tag (bool): Whether its orders carry the caller's tag.
            overrides (dict | None): The order's own values written over the body's, such as its quantity.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(
            path,
            [
                name,
            ],
            None,
            None,
            FixedPricing(None, None),
            keeps_tag,
            overrides=overrides,
        )
        self.name = name
        self.settings = settings

    def settings_problems(self):
        """Every problem with the preset's settings, which by default is none.

        Returns:
            list: One message (str) per problem.
        """
        return []

    def own_memory(self, plan_order):
        """What this part remembers between events, kept in its part record.

        Args:
            plan_order (PlanOrder): The plan order.

        Returns:
            dict: A copy of the memory, empty before anything is remembered.
        """
        return dict(plan_order.part_record(self.path).get('own_memory') or {})

    def remember(self, plan_order, memory, message):
        """Keeps this part's memory in its part record, recorded with a message so a restart replays it.

        Args:
            plan_order (PlanOrder): The plan order.
            memory (dict): The whole memory.
            message (str): Why it changed, for the event log.

        Returns:
            None: This method returns nothing.
        """
        record = plan_order.part_record(self.path)
        record['own_memory'] = memory
        plan_order.set_part_record(self.path, record, message)

    def inventory(self, parent):
        """The net position this part's own fills have built.

        Args:
            parent (ParentOrder): The plan order's parent.

        Returns:
            int: Positive when long.
        """
        net = 0
        for leg in self.own_legs(parent):
            filled = leg.filled_quantity or 0
            if leg.transaction_type == 'BUY':
                net = net + filled
            else:
                net = net - filled
        return net

    def limit_order(self, plan_order, side, price, quantity=None):
        """A limit order of this part's own, on its instrument, with the body's other values.

        Args:
            plan_order (PlanOrder): The plan order.
            side (str): BUY or SELL.
            price (decimal.Decimal): The limit price.
            quantity (int | None): The quantity, or None for the body's.

        Returns:
            PlaceOrderRequest: The order.
        """
        body = dict(self.context(plan_order).body)
        body.pop('price_reference', None)
        body.pop('quantity_reference', None)
        body.pop('trigger_price', None)
        if not self.keeps_tag and 'tag' not in self.overrides:
            body.pop('tag', None)
        body['order_type'] = 'LIMIT'
        body['transaction_type'] = side
        body['price'] = str(price)
        if quantity is not None:
            body['quantity'] = quantity
        return plan_order.concrete_order(plan_order.read_order(body))

    def place_order(self, plan_order, order, started_at):
        """Places one of this part's broker orders at the broker the plan's orders go to.

        Args:
            plan_order (PlanOrder): The plan order.
            order (PlaceOrderRequest): The order.
            started_at (float | None): When the engine took the intent, or None.

        Returns:
            tuple: The broker's answer (dict), its HTTP status (int) and the leg (OrderLeg).
        """
        context = self.context(plan_order)
        broker_name = context.body.get('broker') or plan_order.chosen_broker()
        return context.place_leg(self.path, order, started_at, broker_name, None)

    def expanded(self):
        """This part as it will run, for a dry run's answer: the type it keeps whole and its settings.

        Returns:
            dict: The part's path, presets and kept-whole settings.
        """
        return {
            'order': {
                'path': self.path,
                'presets': list(self.presets),
                'kept_whole': {
                    self.name: dict(self.settings),
                },
            },
        }
