"""Works out when three lifetimes end, from a fixed Wednesday morning and a fixed Sunday.

`Lifetime.ends_at` reads `at_time` as that time on the instrument's next trading day, so 14:30 asked for on a Sunday means Monday at 14:30, and counts `after_minutes` from the moment given. Minutes asked for on a day the instrument does not trade are refused, as today's time stop refuses them. The moments are fixed so the output does not change. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/lifetime/Lifetime/example_1_when_an_order_ends.py
"""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities import moments
from unified_broker_interface.utilities.order_engine.utilities.lifetime import (
    Lifetime,
)

WEDNESDAY = datetime.datetime(2026, 9, 23, 10, 0, 0, tzinfo=moments.INDIA)
SUNDAY = datetime.datetime(2026, 9, 27, 10, 0, 0, tzinfo=moments.INDIA)


class StandInPlanOrder:
    """Stands in for the plan order, which only needs to name its segment here."""

    def trading_segment(self):
        """The segment whose calendar the order's times follow.

        Returns:
            str: `nse_equity`.
        """
        return 'nse_equity'


class WhenAnOrderEndsExample:
    """Prints when each lifetime ends."""

    def shown(self, moment):
        """A Unix time as a day and time in India.

        Args:
            moment (float): The Unix time.

        Returns:
            str: The day and time.
        """
        return datetime.datetime.fromtimestamp(moment, moments.INDIA).strftime('%A %H:%M')

    def run(self):
        """Prints each answer.

        Returns:
            None: This method returns nothing.
        """
        plan_order = StandInPlanOrder()
        good_till_time = Lifetime('14:30', None, 'both', 'cancel')
        time_stop = Lifetime(None, 20, 'working', 'close_filled')
        print(f'14:30 asked for on Wednesday morning ends {self.shown(good_till_time.ends_at(plan_order, WEDNESDAY))}')
        print(f'14:30 asked for on Sunday ends {self.shown(good_till_time.ends_at(plan_order, SUNDAY))}')
        print(f'20 minutes asked for on Wednesday morning ends {self.shown(time_stop.ends_at(plan_order, WEDNESDAY))}')
        try:
            time_stop.ends_at(plan_order, SUNDAY)
        except RefusedRequestError as refusal:
            print(f'20 minutes asked for on Sunday: {refusal.status} {refusal.body["error"]}')
        print(f'As a dry run shows them: {good_till_time.described()} and {time_stop.described()}')


if __name__ == '__main__':
    WhenAnOrderEndsExample().run()
