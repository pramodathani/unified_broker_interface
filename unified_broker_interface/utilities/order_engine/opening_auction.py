"""An order that takes part in the opening call auction."""

import datetime

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.scheduled import Scheduled
from unified_broker_interface.utilities.order_engine.utilities.moments import (
    Moments,
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


class OpeningAuction(Scheduled):
    """An order placed in the pre-open session, so it fills at the single opening price the auction discovers (the Atlas's G1).

    In India a market-on-open or limit-on-open order is simply an order placed while the pre-open collects orders, so this is a scheduled order with the pre-open's rules. The cash market's pre-open, on NSE and BSE, collects market and limit orders from 09:00 until 09:05 and limit orders alone until 09:10. NSE's futures pre-open, for current-month stock and index futures, closes its collection at a random moment between 09:07 and 09:08, so this type stops at 09:07. Options, commodities and currencies have no pre-open and are refused, and so are stop orders and IOC, which the pre-open does not take.

    `at_time` defaults to 09:00:30, half a minute after collection opens. An order that arrives while collection is already open is placed on the next clock tick, and one that arrives after it has closed is refused rather than sent into continuous trading, because that is a different order from the one asked for.

    Attributes:
        COLLECTION_OPENS (datetime.time): When the pre-open starts taking orders.
        DEFAULT_AT_TIME (str): When the order is placed if the caller does not say.
        MARKET_ORDERS_UNTIL (datetime.time): The last moment the pre-open takes a market order.
        CASH_COLLECTION_CLOSES (datetime.time): The last moment the cash pre-open takes a limit order.
        FUTURES_COLLECTION_CLOSES (datetime.time): The last moment this type places a futures order.
    """

    SYNTHETIC_TYPE = 'opening_auction'
    COLLECTION_OPENS = datetime.time(9, 0, 0)
    DEFAULT_AT_TIME = '09:00:30'
    MARKET_ORDERS_UNTIL = datetime.time(9, 5, 0)
    CASH_COLLECTION_CLOSES = datetime.time(9, 10, 0)
    FUTURES_COLLECTION_CLOSES = datetime.time(9, 7, 0)

    def collection_closes(self, order):
        """The moment after which the pre-open no longer takes this order.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.

        Returns:
            datetime.time: The time of day.

        Raises:
            RefusedRequestError: With HTTP 400 when the instrument has no pre-open, or the order is not a plain limit or market order for the day.
        """
        if order.order_type not in AUCTION_ORDER_TYPES:
            raise RefusedRequestError.refusal(
                'the pre-open takes only LIMIT and MARKET orders, not '
                f'{order.order_type}',
                400,
            )
        if order.validity == 'IOC':
            raise RefusedRequestError.refusal(
                'the pre-open does not take IOC orders',
                400,
            )
        instrument, _, _ = self.placement.market_context(
            self.parent.instrument_id,
            False,
            False,
        )
        if instrument.exchange in ('nse', 'bse'):
            if instrument.bare_segment in CASH_SEGMENTS:
                closes = self.CASH_COLLECTION_CLOSES
            elif (
                instrument.exchange == 'nse'
                and instrument.bare_segment in FUTURES_SEGMENTS
            ):
                closes = self.FUTURES_COLLECTION_CLOSES
            else:
                closes = None
        else:
            closes = None
        if closes is None:
            raise RefusedRequestError.refusal(
                f'{instrument.segment or "this instrument"} has no pre-open '
                'auction; a scheduled order at 09:15 is the nearest there is',
                400,
                instrument_id=self.parent.instrument_id,
            )
        if order.order_type == 'MARKET' and self.MARKET_ORDERS_UNTIL < closes:
            return self.MARKET_ORDERS_UNTIL
        return closes

    def moment_today(self, wanted, now):
        """A time of day today, as a moment in India.

        Args:
            wanted (datetime.time): The time of day.
            now (datetime.datetime): Now, in India.

        Returns:
            datetime.datetime: That time today.
        """
        return now.replace(
            hour=wanted.hour,
            minute=wanted.minute,
            second=wanted.second,
            microsecond=0,
        )

    def read_place_at(self, order):
        """When the order is placed: at `at_time`, or at once when collection is already open.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.

        Returns:
            tuple: The moment as an epoch (float) and as text (str).

        Raises:
            RefusedRequestError: With HTTP 400 when the instrument has no pre-open, the order is not one it takes, `at_time` is outside collection, or collection has closed for today.
        """
        closes = self.collection_closes(order)
        now = Moments().now()
        closes_at = self.moment_today(closes, now)
        if now >= closes_at:
            raise RefusedRequestError.refusal(
                f'the pre-open stopped taking this order at {closes}, so it '
                'can no longer join today\'s opening auction',
                400,
            )
        text = self.parent.parameters.get('at_time')
        if text is None:
            wanted = datetime.time.fromisoformat(self.DEFAULT_AT_TIME)
        else:
            try:
                wanted = datetime.time.fromisoformat(str(text))
            except ValueError:
                raise RefusedRequestError.refusal(
                    f'at_time must be a time of day such as 09:00:30, not '
                    f'{text!r}',
                    400,
                )
            if wanted < self.COLLECTION_OPENS or wanted >= closes:
                raise RefusedRequestError.refusal(
                    f'at_time must be from {self.COLLECTION_OPENS} and '
                    f'before {closes}, while the pre-open takes this order, '
                    f'not {text}',
                    400,
                )
        place_at = self.moment_today(wanted, now)
        if place_at <= now:
            return now.timestamp(), now.strftime('%H:%M:%S')
        return place_at.timestamp(), place_at.strftime('%H:%M:%S')
