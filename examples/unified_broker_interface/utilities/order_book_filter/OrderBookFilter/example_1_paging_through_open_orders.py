"""Pages through the day's open orders two at a time, the way `GET /api/orders/details?status=open&limit=2` does.

`GET /api/orders/details` serves one document holding every order of the day. An `OrderBookFilter` reads the query string and narrows that document's `orders` list: `status=open` keeps orders that are not yet complete, cancelled, rejected or expired, `limit` caps the page, and `cursor` skips the entries earlier pages returned. The narrowed document keeps the day's `summary` and gains a `page` object whose `next_cursor` is the `cursor` for the next request, or None on the last page.

This program builds a small order book in memory and the query strings as Werkzeug `MultiDict` objects, which is what Flask's `request.args` is. Nothing touches Redis, because the route reads the document from Redis and only then hands it to the filter.

Notice that five of the seven orders are open, that the three pages return two, two and one of them, and that the last page's `next_cursor` is None.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_book_filter/OrderBookFilter/example_1_paging_through_open_orders.py
"""

from werkzeug.datastructures import MultiDict

from unified_broker_interface.utilities.order_book_filter import (
    OrderBookFilter,
)


class PagingThroughOpenOrdersExample:
    """Requests three pages of open orders and prints each page.

    Attributes:
        document (dict): The day's order book, as the route serves it unfiltered.
    """

    def __init__(self):
        """Builds a seven-order book.

        Returns:
            None: This method returns nothing.
        """
        statuses = [
            (
                '260930000001',
                'COMPLETE',
            ),
            (
                '260930000002',
                'OPEN',
            ),
            (
                '260930000003',
                'TRIGGER PENDING',
            ),
            (
                '260930000004',
                'REJECTED',
            ),
            (
                '260930000005',
                'OPEN',
            ),
            (
                '260930000006',
                'OPEN',
            ),
            (
                '260930000007',
                'open',
            ),
        ]
        orders = []
        for order_id, status in statuses:
            orders.append({
                'order_id': order_id,
                'broker': 'zerodha',
                'status': status,
            })
        self.document = {
            'summary': {
                'orders': len(orders),
            },
            'orders': orders,
        }

    def run(self):
        """Requests pages until the last one and prints each.

        Returns:
            None: This method returns nothing.
        """
        cursor = 0
        while cursor is not None:
            query = MultiDict([
                (
                    'status',
                    'open',
                ),
                (
                    'limit',
                    '2',
                ),
                (
                    'cursor',
                    str(cursor),
                ),
            ])
            order_filter = OrderBookFilter(query)
            print(f'status {order_filter.status}, limit {order_filter.limit}, cursor {order_filter.cursor}, active {order_filter.is_active()}')
            page = order_filter.apply(self.document, 'orders')
            returned = []
            for order in page['orders']:
                returned.append(f'{order["order_id"]} {order["status"]}')
            print(f'  orders: {returned}')
            print(f'  page: {page["page"]}; summary kept: {page["summary"]}')
            cursor = page['page']['next_cursor']


if __name__ == '__main__':
    PagingThroughOpenOrdersExample().run()
