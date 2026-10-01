"""Shows which states each choice of `applies_to` bounds.

`Lifetime.bounds` says whether an order in a state should end when its time comes: `waiting` bounds the time before the order is sent, which covers both `pending` and `waiting`, `working` the time after, and `both` either. An order that is already done is never ended again. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/lifetime/Lifetime/example_2_which_part_of_its_life.py
"""

from unified_broker_interface.utilities.order_engine.utilities.lifetime import (
    Lifetime,
)


class WhichPartOfItsLifeExample:
    """Prints which states each lifetime bounds."""

    def run(self):
        """Prints a row per lifetime.

        Returns:
            None: This method returns nothing.
        """
        states = [
            'pending',
            'waiting',
            'working',
            'done',
        ]
        for applies_to in ('waiting', 'working', 'both'):
            lifetime = Lifetime('15:00', None, applies_to, 'cancel')
            bounded = []
            for state in states:
                if lifetime.bounds(state):
                    bounded.append(state)
            print(f'{applies_to}: ends an order that is {", ".join(bounded)}')
        print(f'As a dry run shows one: {Lifetime(None, 45, "both", "marketable").described()}')


if __name__ == '__main__':
    WhichPartOfItsLifeExample().run()
