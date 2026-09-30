"""Shows the requests a price trigger refuses, a dry run, and what state the parent is left in when its child order is rejected.

A `PriceTrigger` checks its parameters when it is armed and answers a bad one with a `RefusedRequestError` carrying HTTP 400: a missing or non-positive `trigger_price`, an unknown `trigger_direction` or `trigger_on`, and `trigger_on: held` without a `hold_seconds` above zero. A type that chooses its own watched price sets `TAKES_TRIGGER_ON` to False and refuses `trigger_on` altogether. A dry run is checked the same way and answered with the request that would have been sent, without recording anything.

The program then calls `fire` directly, as `on_price_tick` would, with a stand-in placement whose broker rejects the order, and prints the state the parent is recorded in. It also shows `state_after_firing` for every outcome, including a parent that was already `protecting`, `exit_side` for both sides, and how `has_fired` tells that a trigger fired from its legs alone, which is how a parent rebuilt after a restart knows, since `triggered_at` is kept only in Redis.

The stand-ins are a placement that builds requests and answers with a rejection, an event log that keeps events in a list, and a parent store that ignores saves. Nothing is sent anywhere.

Run it from the project root:

    python examples/unified_broker_interface/utilities/order_engine/utilities/price_trigger/PriceTrigger/example_3_refusals_and_what_firing_leaves_behind.py
"""

import decimal
import logging

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.order_leg import (
    OrderLeg,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.price_trigger import (
    PriceTrigger,
)

INSTRUMENT_ID = '5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d'


class TouchBuyOrder(PriceTrigger):
    """A buy that waits for the price to fall to a level and then takes the best offer."""

    SYNTHETIC_TYPE = 'touch_buy'

    def child_order(self, order, view):
        """A limit at the best offer.

        Args:
            order (PlaceOrderRequest): The order the caller asked for.
            view (MarketView): The traded instrument's quote.

        Returns:
            PlaceOrderRequest | None: The order to send, or None when there is no offer.
        """
        offer = view.best_offer()
        if offer is None:
            return None
        return self.priced(order, offer)


class OwnPriceOrder(TouchBuyOrder):
    """A trigger type that always watches the offer and so does not let the caller choose."""

    SYNTHETIC_TYPE = 'own_price'
    TAKES_TRIGGER_ON = False


class StandInInstrument:
    """The catalogue entry the placement returns.

    Attributes:
        handles (dict): Each broker's handle, by broker name.
    """

    def __init__(self):
        """Builds an instrument traded in ticks of 0.05.

        Returns:
            None: This method returns nothing.
        """
        self.handles = {
            'fyers': {
                'tick_size': '0.05',
            },
        }


class StandInBrokerRequest:
    """The request built for a broker.

    Attributes:
        tag (str | None): The tag the request carries.
        fields (dict): What would be sent.
    """

    def __init__(self, fields):
        """Builds the request.

        Args:
            fields (dict): What would be sent.

        Returns:
            None: This method returns nothing.
        """
        self.tag = None
        self.fields = fields

    def shown(self):
        """The request as the event log keeps it.

        Returns:
            dict: The fields.
        """
        return self.fields


class StandInPrepared:
    """An order with a broker chosen and its request built.

    Attributes:
        broker_name (str): The chosen broker.
        broker_request (StandInBrokerRequest): The request.
        identifier_sent (str): The symbol the request names.
    """

    def __init__(self, broker_name, broker_request):
        """Builds the prepared order.

        Args:
            broker_name (str): The chosen broker.
            broker_request (StandInBrokerRequest): The request.

        Returns:
            None: This method returns nothing.
        """
        self.broker_name = broker_name
        self.broker_request = broker_request
        self.identifier_sent = 'NSE:SBIN-EQ'


class RejectingPlacement:
    """Stands in for `EnginePlacement`: it builds requests for Fyers, and the broker rejects every order sent."""

    def market_context(self, instrument_id, wants_quote, wants_positions):
        """Returns the instrument, and no quote or positions.

        Args:
            instrument_id (str): The instrument.
            wants_quote (bool): Whether the quote is needed.
            wants_positions (bool): Whether the positions are needed.

        Returns:
            tuple: The instrument (StandInInstrument), None and None.
        """
        return StandInInstrument(), None, None

    def prepare(self, order, instrument_id, broker_name=None):
        """Builds the request for Fyers.

        Args:
            order (PlaceOrderRequest): The order.
            instrument_id (str): The instrument.
            broker_name (str | None): The broker the order must go to.

        Returns:
            StandInPrepared: The prepared order.
        """
        fields = {
            'side': order.transaction_type,
            'type': order.order_type,
            'qty': order.quantity,
            'limitPrice': str(order.price),
        }
        return StandInPrepared(broker_name or 'fyers', StandInBrokerRequest(fields))

    def dry_run_answer(self, prepared, started_at):
        """Answers with the request that would have been sent.

        Args:
            prepared (StandInPrepared): The prepared order.
            started_at (float): When the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        body = {
            'broker': prepared.broker_name,
            'outcome': 'dry_run',
            'request': prepared.broker_request.shown(),
        }
        return body, 200

    def send(self, prepared, started_at):
        """Answers as a broker that rejected the order.

        Args:
            prepared (StandInPrepared): The prepared order.
            started_at (float): When the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        body = {
            'broker': prepared.broker_name,
            'outcome': 'rejected',
            'order_id': None,
            'status_message': 'RMS: insufficient margin',
        }
        return body, 200


class ListEventLog:
    """Stands in for the event log, keeping every event in a list.

    Attributes:
        events (list): The events recorded, oldest first.
    """

    def __init__(self):
        """Builds an empty log.

        Returns:
            None: This method returns nothing.
        """
        self.events = []

    def record(self, event):
        """Keeps one event.

        Args:
            event (dict): The event.

        Returns:
            None: This method returns nothing.
        """
        self.events.append(event)


class IgnoringParentStore:
    """Stands in for the Redis copy of the parent, and writes nothing."""

    def save(self, parent):
        """Ignores one save.

        Args:
            parent (ParentOrder): The parent.

        Returns:
            None: This method returns nothing.
        """


class RefusalsExample:
    """Arms triggers with bad parameters, runs a dry run, and fires one whose child order is rejected.

    Attributes:
        placement (RejectingPlacement): The stand-in placement.
        event_log (ListEventLog): The stand-in event log.
    """

    def __init__(self):
        """Builds the stand-ins.

        Returns:
            None: This method returns nothing.
        """
        self.placement = RejectingPlacement()
        self.event_log = ListEventLog()

    def trigger(self, parameters, order_class=TouchBuyOrder, dry_run=False):
        """Builds a buy of 100 shares with the given parameters.

        Args:
            parameters (dict): The parent's parameters.
            order_class (type): The trigger class to build.
            dry_run (bool): Whether the caller asked for a dry run.

        Returns:
            TouchBuyOrder: The trigger.
        """
        parent = ParentOrder('7c1d2e3f-0000-4000-8000-000000000003')
        parent.synthetic_type = order_class.SYNTHETIC_TYPE
        parent.instrument_id = INSTRUMENT_ID
        parent.body = {
            'instrument_id': INSTRUMENT_ID,
            'transaction_type': 'BUY',
            'product': 'MIS',
            'order_type': 'MARKET',
            'quantity': 100,
            'dry_run': dry_run,
        }
        parent.parameters = parameters
        return order_class(
            parent,
            self.placement,
            self.event_log,
            IgnoringParentStore(),
            logging.getLogger('example'),
        )

    def show_refusals(self):
        """Arms a trigger with each bad parameter and prints the refusal.

        Returns:
            None: This method returns nothing.
        """
        cases = [
            (
                'no trigger_price',
                {},
                TouchBuyOrder,
            ),
            (
                'trigger_price of zero',
                {
                    'trigger_price': 0,
                },
                TouchBuyOrder,
            ),
            (
                'trigger_price of "soon"',
                {
                    'trigger_price': 'soon',
                },
                TouchBuyOrder,
            ),
            (
                'an unknown direction',
                {
                    'trigger_price': 812,
                    'trigger_direction': 'sideways',
                },
                TouchBuyOrder,
            ),
            (
                'an unknown trigger_on',
                {
                    'trigger_price': 812,
                    'trigger_on': 'vwap',
                },
                TouchBuyOrder,
            ),
            (
                'held without hold_seconds',
                {
                    'trigger_price': 812,
                    'trigger_on': 'held',
                },
                TouchBuyOrder,
            ),
            (
                'trigger_on for a type that chooses its own price',
                {
                    'trigger_price': 812,
                    'trigger_on': 'bid',
                },
                OwnPriceOrder,
            ),
        ]
        for label, parameters, order_class in cases:
            try:
                self.trigger(parameters, order_class).run({}, 0.0)
            except RefusedRequestError as error:
                print(f'{label}: {error.status} {error.body["error"]}')
        held = self.trigger(
            {
                'trigger_price': 812,
                'trigger_on': 'held',
                'hold_seconds': '-3',
            },
        )
        try:
            held.read_hold_seconds()
        except RefusedRequestError as error:
            print(f'hold_seconds of -3 read on its own: {error.status} {error.body["error"]}')

    def run(self):
        """Prints the refusals, the dry run, and what firing into a rejection leaves.

        Returns:
            None: This method returns nothing.
        """
        self.show_refusals()
        dry = self.trigger(
            {
                'trigger_price': 812,
            },
            dry_run=True,
        )
        answer, status = dry.run({}, 0.0)
        print(f'Dry run {status}: {answer}; events recorded {len(self.event_log.events)}')

        trigger = self.trigger(
            {
                'trigger_price': 812,
                'tick_size': '0.05',
            },
        )
        trigger.record_received()
        order = trigger.read_order(trigger.parent.body)
        child = trigger.priced(order, decimal.Decimal('811.95'))
        fired = trigger.fire(child, decimal.Decimal('811.90'), decimal.Decimal('812'))
        print(f'fire returned {fired}; parent is now {trigger.parent.state}')
        print(f'  why: {self.event_log.events[-1]["status_message"]}')
        print(f'  has_fired from its entry leg: {trigger.has_fired()}')

        for outcome in [
            'accepted',
            'rejected',
            'unknown',
            None,
        ]:
            print(f'state_after_firing({outcome!r}) from received: {trigger.state_after_firing(outcome)}')
        trigger.parent.state = 'protecting'
        print(f'state_after_firing(\'accepted\') from protecting: {trigger.state_after_firing("accepted")}')
        print(f'exit_side of BUY: {trigger.exit_side("BUY")}, of SELL: {trigger.exit_side("SELL")}')

        rebuilt = self.trigger(
            {
                'trigger_price': 812,
            },
        )
        backstop = OrderLeg('leg-1', 'backstop')
        rebuilt.parent.legs = [
            backstop,
        ]
        print(f'Rebuilt parent with only a backstop leg has fired: {rebuilt.has_fired()}')
        rebuilt.parent.legs.append(OrderLeg('leg-2', 'entry'))
        print(f'Rebuilt parent with an entry leg too has fired: {rebuilt.has_fired()}')


if __name__ == '__main__':
    RefusalsExample().run()
