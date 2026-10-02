"""Reads a Using join that gives each rung of a three-step ladder its own bracket, and shows the copies it made, each copy's share and how a dry run shows it.

The plan reader builds one copy of the order per rung, with the bracket preset written onto it, so each copy is a whole Then join of an entry and its exits. `UsingPart.quantities` shares the order out as the ladder would, the first rungs taking the remainder, and `mains` names each copy's entry, which `start` gives its rung's price. A Using join is never resized, so `set_target` changes nothing. Nothing is read from Redis or sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/using_part/UsingPart/example_1_a_ladder_of_brackets.py
"""

from unified_broker_interface.utilities.order_engine.utilities.plan_reader import (
    PlanReader,
)


class ALadderOfBracketsExample:
    """Reads one Using join and prints what it holds."""

    def run(self):
        """Prints the copies, the shares and the dry run's view.

        Returns:
            None: This method returns nothing.
        """
        reader = PlanReader('BUY')
        join = reader.read(
            {
                'using': {
                    'order': {
                        'execution': [
                            {
                                'ladder': {
                                    'from_price': 1000,
                                    'to_price': 990,
                                    'steps': 3,
                                },
                            },
                        ],
                    },
                    'each_piece': {
                        'presets': [
                            {
                                'bracket': {
                                    'stop_price': 980,
                                    'stop_limit_price': 978,
                                    'target_price': 1020,
                                },
                            },
                        ],
                    },
                },
            }
        )
        print(f'problems: {reader.problems}')
        print(f'copies: {[type(child).__name__ for child in join.children]}')
        print(f'entries: {[main.path for main in join.mains]}')
        print(f'shares of 10: {join.quantities(10)}')
        print(f'set_target changes nothing: {join.set_target(None, 4)}')
        expanded = join.expanded()['using']
        print(f'dry run: execution {expanded["execution"]}, {len(expanded["children"])} children, the first a {list(expanded["children"][0])[0]} join')


if __name__ == '__main__':
    ALadderOfBracketsExample().run()
