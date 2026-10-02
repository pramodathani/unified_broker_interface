"""Reads two Repeat joins: one sending a copy every trading day at 09:20, and one that stops sending copies once the price reaches a level.

With `every_trading_day_at`, every copy waits on a `trading_day_at` trigger for that time on its own trading day, copy 0 on the first, and each copy spans days, which keeps the plan across trading days. With `until`, every copy is given a lifetime that ends it while it is still waiting once the condition holds, so the repeating stops, while copies already sent are left resting. Exactly one of `every_minutes` and `every_trading_day_at` is given, and a copy with `until` takes no lifetime of its own. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/repeat_part/RepeatPart/example_3_every_trading_day_and_until.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class EveryTradingDayAndUntilExample:
    """Reads a daily repeat, a repeat with until, and two refused ones."""

    def run(self):
        """Prints each copy's trigger and lifetime, and the refusals.

        Returns:
            None: This method returns nothing.
        """
        daily = PlanReader('BUY').read(
            {
                'repeat': {
                    'child': {
                        'order': {},
                    },
                    'times': 3,
                    'every_trading_day_at': '09:20',
                },
            }
        )
        print('Daily:', daily.expanded()['repeat']['every_trading_day_at'])
        for part in daily.order_parts():
            print(f'  {part.path}: {part.trigger.described()}, spans days {part.spans_days}')
        stopping = PlanReader('BUY').read(
            {
                'repeat': {
                    'child': {
                        'order': {},
                    },
                    'times': 3,
                    'every_minutes': 5,
                    'until': {
                        'price_crosses': {
                            'level': 1010,
                            'direction': 'at_or_above',
                        },
                    },
                },
            }
        )
        print('Until:', stopping.expanded()['repeat']['until'])
        for part in stopping.order_parts():
            print(f'  {part.path}: lifetime {part.lifetime.described()}')
        refusals = [
            {
                'repeat': {
                    'child': {
                        'order': {},
                    },
                    'times': 2,
                    'every_minutes': 5,
                    'every_trading_day_at': '09:20',
                },
            },
            {
                'repeat': {
                    'child': {
                        'order': {
                            'lifetime': [
                                {
                                    'after_minutes': 10,
                                },
                            ],
                        },
                    },
                    'times': 2,
                    'every_minutes': 5,
                    'until': {
                        'time_after': '15:00',
                    },
                },
            },
        ]
        for plan in refusals:
            reader = PlanReader('BUY')
            reader.read(plan)
            for problem in reader.problems:
                print(f'  {problem["rule"]}: {problem["message"]}')


if __name__ == '__main__':
    EveryTradingDayAndUntilExample().run()
