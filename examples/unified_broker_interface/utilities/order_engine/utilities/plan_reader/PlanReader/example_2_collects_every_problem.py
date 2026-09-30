"""Reads four plans that cannot run and prints every problem the reader finds in each.

`PlanReader` does not stop at the first problem. It walks the whole plan and records each one with the path of the part it is in, the name of the rule it breaks and a message for the caller, so a caller can fix everything in one go. This program reads a plan that is not an object, a plan that names a join, a plan that names a key no node has, and an order with three problems of its own.

The joins, such as `then`, are part of the design and are recognised, so the reader says they are not built yet rather than that they are unknown.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_reader/PlanReader/example_2_collects_every_problem.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class CollectsEveryProblemExample:
    """Reads four faulty plans and prints their problems.

    Attributes:
        reader (PlanReader): The reader.
    """

    def __init__(self):
        """Builds the reader.

        Returns:
            None: This method returns nothing.
        """
        self.reader = PlanReader()

    def show(self, title, plan):
        """Reads one plan and prints every problem found.

        Args:
            title (str): A name for the plan.
            plan (object): The plan.

        Returns:
            None: This method returns nothing.
        """
        root = self.reader.read(plan)
        print(f'{title}: part {root}, {len(self.reader.problems)} problem(s)')
        for problem in self.reader.problems:
            print(f"  {problem['path']} [{problem['rule']}]: {problem['message']}")

    def run(self):
        """Reads all four plans.

        Returns:
            None: This method returns nothing.
        """
        self.show(
            'Not an object',
            'buy 10',
        )
        self.show(
            'A join',
            {
                'then': {},
            },
        )
        self.show(
            'An unknown node',
            {
                'bracket': {},
            },
        )
        self.show(
            'An order with three problems',
            {
                'order': {
                    'side': 'buy',
                    'presets': [
                        {
                            'peg': {},
                        },
                        {
                            'simple': {
                                'broker': 'zerodha',
                            },
                        },
                    ],
                },
            },
        )


if __name__ == '__main__':
    CollectsEveryProblemExample().run()
