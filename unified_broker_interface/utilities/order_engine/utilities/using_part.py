"""The Using join: every piece an execution would send handed to a whole plan of its own, such as every rung of a ladder its own bracket."""

from unified_broker_interface.utilities.order_engine.utilities.ladder_execution import (
    LadderExecution,
)
from unified_broker_interface.utilities.order_engine.utilities.together_part import (
    TogetherPart,
)


class UsingPart(TogetherPart):
    """A branch of a plan that splits one order into the pieces its execution would send, and runs each piece as a whole plan.

    The plan reader builds one copy of the order per piece, with the `each_piece` presets and slot values written onto it, so a copy may be a whole join, such as a bracket around the piece. This class works out each copy's share of the quantity, and for a ladder its rung's price, with the execution's own arithmetic, and starts each copy with them; the copies then run side by side, as a together join's children do. For a TWAP or front-loaded execution the reader gives each copy an `elapsed` trigger for its slice's turn.

    Attributes:
        execution (LadderExecution | TimedSlicesExecution): The execution whose pieces become the copies.
        mains (list): Each copy's main order, the one that trades the piece, in piece order.
    """

    def __init__(self, path, children, execution, mains):
        """Builds the join from copies the plan reader has already made.

        Args:
            path (str): Where the join sits in the plan.
            children (list): The copies, one per piece, in piece order.
            execution (LadderExecution | TimedSlicesExecution): The execution whose pieces become the copies.
            mains (list): Each copy's main order.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(path, children, False, False, 'all')
        self.execution = execution
        self.mains = mains

    def quantities(self, total):
        """Each piece's share of the order, as the execution would send them.

        Args:
            total (int): The order's quantity.

        Returns:
            list: One quantity per piece.
        """
        if isinstance(self.execution, LadderExecution):
            return self.execution.quantities(total)
        return self.execution.slice_quantities(total, {})

    def start(self, plan_order, target, started_at, quotes):
        """Starts every copy with its piece's share, and for a ladder its rung's price.

        Args:
            plan_order (PlanOrder): The plan order.
            target (int | None): The quantity to split, or None for the order's own.
            started_at (float | None): When the engine took the intent, or None.
            quotes (dict): The quotes to price from.

        Returns:
            list: One `(path, answer, status)` per broker order placed now.
        """
        first_main = self.mains[0]
        total = target
        if total is None:
            total = plan_order.read_order(first_main.context(plan_order).body).quantity
        shares = self.quantities(total)
        prices = None
        if isinstance(self.execution, LadderExecution):
            prices = self.execution.rung_prices(first_main.context(plan_order), first_main._sending_side(plan_order))
        placed = []
        for index, child in enumerate(self.children):
            if prices is not None:
                main = self.mains[index]
                record = plan_order.part_record(main.path)
                record['piece_price'] = str(prices[index])
                plan_order.set_part_record(main.path, record, f'the plan\'s {main.path} part is rung {index + 1}, at {prices[index]}')
            placed = placed + child.start(plan_order, shares[index], started_at, quotes)
        return placed

    def set_target(self, plan_order, target):
        """Leaves the copies as they were sized, since a Using join is never resized: the reader refuses it under a Then join or a reducing Either join.

        Args:
            plan_order (PlanOrder): Unused.
            target (int): Unused.

        Returns:
            None: This method returns nothing.
        """
        del plan_order, target

    def expanded(self):
        """This join as it will run, for a dry run's answer.

        Returns:
            dict: The execution and the copies.
        """
        children = []
        for child in self.children:
            children.append(child.expanded())
        return {
            'using': {
                'path': self.path,
                'execution': self.execution.described(),
                'children': children,
            },
        }
