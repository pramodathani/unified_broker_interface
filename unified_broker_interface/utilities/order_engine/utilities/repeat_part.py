"""The Repeat join: one order sent again and again on a schedule, such as an accumulation's purchases."""

from unified_broker_interface.utilities.order_engine.utilities.together_part import (
    TogetherPart,
)


class RepeatPart(TogetherPart):
    """A branch of a plan that sends one order `times` times, each copy `every_minutes` after the one before, the first at once.

    The plan reader builds one copy per time, each with its own path and, after the first, an `elapsed` trigger for its turn, so the copies run together and independently as a together join's children do; this class only remembers the schedule, for a dry run's answer. A copy that does not fill is left resting, as today's accumulation leaves a purchase.

    Attributes:
        times (int): How many copies are sent.
        every_minutes (float): The minutes between one copy and the next.
    """

    def __init__(self, path, children, times, every_minutes):
        """Builds the join from copies the plan reader has already made.

        Args:
            path (str): Where the join sits in the plan.
            children (list): The copies, in the order they are sent.
            times (int): How many copies are sent.
            every_minutes (float): The minutes between one copy and the next.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(path, children, False, False, 'all')
        self.times = times
        self.every_minutes = every_minutes

    def expanded(self):
        """This join as it will run, for a dry run's answer.

        Returns:
            dict: The schedule and the copies.
        """
        children = []
        for child in self.children:
            children.append(child.expanded())
        return {
            'repeat': {
                'path': self.path,
                'times': self.times,
                'every_minutes': self.every_minutes,
                'children': children,
            },
        }
