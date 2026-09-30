"""Narrows the trade book to one order engine parent's trades, and to a list of order ids, and checks single trades against a filter.

The same `OrderBookFilter` serves `GET /api/orders/trades`, whose document holds a `trades` list. A caller that placed a parent order through the order engine can ask for `parent_id` to see only the fills of its child orders, or for `order_id`, given more than once or comma-separated, to see the fills of particular orders. Several filters together must all match. With no filter at all, `is_active` is False and the route serves the document unchanged.

This program builds a small trade book and the query strings in memory, as Werkzeug `MultiDict` objects like Flask's `request.args`. It also calls `matches` on single trades and `whole_number` on its own, which the constructor uses to read `limit` and `cursor`. Nothing touches Redis.

Notice that the comma-separated and repeated `order_id` values are merged into one set, that the parent filter and the broker filter together keep only one trade, and that a filter built from an empty query string is not active.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_book_filter/OrderBookFilter/example_2_finding_one_parents_trades.py
"""

from werkzeug.datastructures import MultiDict

from unified_broker_interface.utilities.order_book_filter import (
    OrderBookFilter,
)


class FindingOneParentsTradesExample:
    """Filters a five-trade book three ways.

    Attributes:
        document (dict): The day's trade book.
    """

    def __init__(self):
        """Builds a five-trade book.

        Returns:
            None: This method returns nothing.
        """
        self.document = {
            'trades': [
                self.trade('T1', '1001', 'zerodha', 'parent-a'),
                self.trade('T2', '1001', 'zerodha', 'parent-a'),
                self.trade('T3', '2002', 'dhan', 'parent-a'),
                self.trade('T4', '3003', 'dhan', 'parent-b'),
                self.trade('T5', '4004', 'fyers', None),
            ],
        }

    @staticmethod
    def trade(trade_id, order_id, broker, parent_id):
        """Builds one trade.

        Args:
            trade_id (str): The trade id.
            order_id (str): The order it filled.
            broker (str): The broker.
            parent_id (str | None): The order engine parent, or None for an order placed directly.

        Returns:
            dict: The trade.
        """
        return {
            'trade_id': trade_id,
            'order_id': order_id,
            'broker': broker,
            'engine_parent_id': parent_id,
        }

    def show(self, label, query):
        """Filters the trade book with one query string and prints the trades kept.

        Args:
            label (str): What the query asks for, for the printout.
            query (MultiDict): The query string arguments.

        Returns:
            OrderBookFilter: The filter built from the query string.
        """
        order_filter = OrderBookFilter(query)
        narrowed = order_filter.apply(self.document, 'trades')
        kept = []
        for trade in narrowed['trades']:
            kept.append(trade['trade_id'])
        print(f'{label}: active {order_filter.is_active()}, kept {kept}, matched {narrowed["page"]["matched"]}')
        return order_filter

    def run(self):
        """Filters by order ids, by parent and broker, and by nothing.

        Returns:
            None: This method returns nothing.
        """
        by_orders = self.show('By order ids', MultiDict([
            (
                'order_id',
                '1001,2002',
            ),
            (
                'order_id',
                '4004',
            ),
        ]))
        print(f'  order ids read: {sorted(by_orders.order_ids)}')
        by_parent = self.show('By parent and broker', MultiDict([
            (
                'parent_id',
                'parent-a',
            ),
            (
                'broker',
                'dhan',
            ),
        ]))
        print(f'  parent {by_parent.parent_id}, broker {by_parent.broker}, intent {by_parent.intent_id}')
        for trade in self.document['trades']:
            print(f'  {trade["trade_id"]} matches: {by_parent.matches(trade)}')
        self.show('No filter', MultiDict())
        print(f'whole_number("25", "limit", 1, 100) = {by_parent.whole_number("25", "limit", 1, 100)}')
        print(f'whole_number("", "limit", 1, 100) = {by_parent.whole_number("", "limit", 1, 100)}')


if __name__ == '__main__':
    FindingOneParentsTradesExample().run()
