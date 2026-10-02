"""Validates cancels of an order the engine manages, named by `parent_id`, and builds the engine command each one becomes.

`DELETE /api/orders/cancel` takes `parent_id` for an order the order engine manages, such as an armed trigger or a bracket plan whose exits have not been sent, because those have no broker order id to name them by. Naming only the parent cancels the whole of it, and naming a `part` path as well, as `GET /api/orders/parents` shows it, cancels one part of a plan. `command_arguments` gives the arguments of the engine's `cancel_parent` command, carrying `part` only when one is named and `dry_run` only when it is true.

`dry_run` is read from the body first and from the query string second, which a MultiDict stands in for, as it does inside Flask. Nothing is sent to the engine.

Run it from the project root:

    python examples/unified_broker_interface/utilities/broker_orders/utilities/parent_cancel/ParentCancel/example_1_cancel_a_plan_part.py
"""

import werkzeug.datastructures

from unified_broker_interface.utilities.broker_orders.utilities.parent_cancel import (
    ParentCancel,
)

PARENT_ID = 'P-00000000000040008000000000000001'
STOP_PART = 'root.each_fill.children.0'


class CancelAPlanPartExample:
    """Validates four cancels and prints the engine command's arguments for each.

    Attributes:
        empty_query (werkzeug.datastructures.MultiDict): A query string with nothing in it.
        dry_run_query (werkzeug.datastructures.MultiDict): A query string asking for a dry run.
    """

    def __init__(self):
        """Builds the two query strings the cancels are read with.

        Returns:
            None: This method returns nothing.
        """
        self.empty_query = werkzeug.datastructures.MultiDict()
        self.dry_run_query = werkzeug.datastructures.MultiDict([
            (
                'dry_run',
                'true',
            ),
        ])

    def show(self, title, cancel):
        """Prints the parsed fields of one cancel and its command arguments.

        Args:
            title (str): What the cancel is.
            cancel (ParentCancel): The validated cancel.

        Returns:
            None: This method returns nothing.
        """
        print(title)
        print(f'  Parent: {cancel.parent_id}')
        print(f'  Part: {cancel.part}')
        print(f'  Dry run: {cancel.dry_run}')
        print(f'  cancel_parent arguments: {cancel.command_arguments()}')

    def run(self):
        """Validates the whole parent, one part, and a dry run from the body and from the query string.

        Returns:
            None: This method returns nothing.
        """
        whole_parent = ParentCancel(
            {
                'parent_id': PARENT_ID,
            },
            self.empty_query,
        )
        self.show('The whole parent:', whole_parent)
        stop_part = ParentCancel(
            {
                'parent_id': PARENT_ID,
                'part': STOP_PART,
            },
            self.empty_query,
        )
        self.show('The stop of the plan:', stop_part)
        dry_run_in_body = ParentCancel(
            {
                'parent_id': PARENT_ID,
                'part': STOP_PART,
                'dry_run': True,
            },
            self.empty_query,
        )
        self.show('The stop, as a dry run named in the body:', dry_run_in_body)
        dry_run_in_query = ParentCancel(
            {
                'parent_id': PARENT_ID,
            },
            self.dry_run_query,
        )
        self.show('The whole parent, as a dry run named in the query string:', dry_run_in_query)
        body_wins = ParentCancel(
            {
                'parent_id': PARENT_ID,
                'dry_run': False,
            },
            self.dry_run_query,
        )
        self.show('The body says false and the query string says true, so the body wins:', body_wins)


if __name__ == '__main__':
    CancelAPlanPartExample().run()
