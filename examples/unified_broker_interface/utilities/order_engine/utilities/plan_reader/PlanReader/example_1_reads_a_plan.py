"""Reads a valid plan into its root part and prints the part as it would run.

`PlanReader` turns the `plan` object of a `plan` order into parts. Each part gets a path from its place in the plan's tree, starting at `root`, and that path is what its broker orders and its state are kept under. This program reads a plan of one order built from the `simple` preset, and a plan whose order names no presets at all, and prints the part each one becomes, with every slot's default written out.

Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/plan_reader/PlanReader/example_1_reads_a_plan.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class ReadsAPlanExample:
    """Reads two valid plans and prints the parts they become.

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
        """Reads one plan and prints the part it becomes.

        Args:
            title (str): A name for the plan.
            plan (dict): The plan.

        Returns:
            None: This method returns nothing.
        """
        root = self.reader.read(plan)
        print(f'{title}:')
        print(f'  path {root.path}, presets {root.presets}, problems {self.reader.problems}')
        print(f"  slots {root.expanded()['order']['slots']}")

    def run(self):
        """Reads both plans.

        Returns:
            None: This method returns nothing.
        """
        self.show(
            'One simple order',
            {
                'order': {
                    'presets': [
                        {
                            'simple': {},
                        },
                    ],
                },
            },
        )
        self.show(
            'An order with no presets',
            {
                'order': {},
            },
        )


if __name__ == '__main__':
    ReadsAPlanExample().run()
