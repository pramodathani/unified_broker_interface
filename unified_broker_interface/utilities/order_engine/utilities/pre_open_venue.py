"""The venue that places an order in the pre-open session, so it trades at the single opening price."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
)
from unified_broker_interface.utilities.order_engine.utilities.trading_days import (
    TradingDays,
)

CASH_SEGMENTS = (
    'equities',
    'exchange_traded_funds',
)
FUTURES_SEGMENTS = (
    'equity_futures',
    'equity_index_futures',
)
AUCTION_ORDER_TYPES = (
    'LIMIT',
    'MARKET',
)
COLLECTION_OPENS = datetime.time(9, 0, 0)
MARKET_ORDERS_UNTIL = datetime.time(9, 5, 0)
CASH_COLLECTION_CLOSES = datetime.time(9, 10, 0)
FUTURES_COLLECTION_CLOSES = datetime.time(9, 7, 0)


class PreOpenVenue:
    """A plan order's venue: the pre-open session, which collects orders before the open and fills them at the price its auction discovers.

    It keeps the rules of today's opening auction type. The cash market's pre-open on NSE and BSE takes market and limit orders from 09:00 until 09:05 and limit orders alone until 09:10; NSE's futures pre-open, for stock and index futures, closes its collection at a random moment after 09:07, so orders stop at 09:07. Options, commodities and currencies have no pre-open, and stop orders and IOC are not taken. The order is sent at `at_time`, through a `time_from` trigger the plan reader adds, so one that arrives while collection is already open goes at once; one that arrives after collection has closed on a trading day is refused rather than sent into continuous trading.

    Attributes:
        at_time (str): The time of day, `HH:MM:SS`, the order is sent at.
    """

    def __init__(self, at_time):
        """Builds the venue from a time the plan reader has already checked.

        Args:
            at_time (str): The time of day the order is sent at.

        Returns:
            None: This method returns nothing.
        """
        self.at_time = at_time

    def collection_closes(self, context):
        """When the pre-open stops taking this order, for its instrument and order type.

        Args:
            context (OrderContext): The order's view of the plan order.

        Returns:
            datetime.time: The last moment it is taken.

        Raises:
            RefusedRequestError: With HTTP 400 when the order type or validity is not taken, or the instrument has no pre-open.
        """
        order_type = str(context.body.get('order_type') or '').upper()
        if order_type not in AUCTION_ORDER_TYPES:
            raise RefusedRequestError.refusal(f'the pre-open takes only LIMIT and MARKET orders, not {order_type}', 400)
        if str(context.body.get('validity') or '').upper() == 'IOC':
            raise RefusedRequestError.refusal('the pre-open does not take IOC orders', 400)
        instrument, _, _ = context.placement.market_context(context.instrument_id, False, False)
        closes = None
        if instrument.exchange in ('nse', 'bse') and instrument.bare_segment in CASH_SEGMENTS:
            closes = CASH_COLLECTION_CLOSES
        elif instrument.exchange == 'nse' and instrument.bare_segment in FUTURES_SEGMENTS:
            closes = FUTURES_COLLECTION_CLOSES
        if closes is None:
            raise RefusedRequestError.refusal(
                f'{instrument.segment or "this instrument"} has no pre-open auction; a scheduled order at 09:15 is the nearest there is',
                400,
                instrument_id=context.instrument_id,
            )
        if order_type == 'MARKET' and MARKET_ORDERS_UNTIL < closes:
            return MARKET_ORDERS_UNTIL
        return closes

    def check(self, context, now=None):
        """Refuses an order the pre-open would not take, or one too late for today's collection.

        Args:
            context (OrderContext): The order's view of the plan order.
            now (datetime.datetime | None): The moment to reckon from, or None for now.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 400 when the order is not one the pre-open takes, `at_time` falls outside collection, or collection has closed on a trading day.
        """
        closes = self.collection_closes(context)
        wanted = datetime.time.fromisoformat(self.at_time)
        if wanted < COLLECTION_OPENS or wanted >= closes:
            raise RefusedRequestError.refusal(
                f'at_time must be from {COLLECTION_OPENS} and before {closes}, while the pre-open takes this order, not {self.at_time}',
                400,
            )
        if now is None:
            now = Moments().now()
        segment = context.trading_segment()
        trading_days = TradingDays()
        if not trading_days.is_trading_day(segment, now.date()):
            return
        closes_at = now.replace(hour=closes.hour, minute=closes.minute, second=closes.second, microsecond=0)
        if now >= closes_at:
            next_day = trading_days.next_trading_day(segment, now.date())
            raise RefusedRequestError.refusal(
                f'the pre-open stopped taking this order at {closes}, so it can no longer join today\'s opening auction; the next is on {next_day.isoformat()}',
                400,
            )

    def described(self):
        """This venue as a dry run shows it.

        Returns:
            dict: The session and the time.
        """
        return {
            'session': 'pre_open',
            'at_time': self.at_time,
        }
