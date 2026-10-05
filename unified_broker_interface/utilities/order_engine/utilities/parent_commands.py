"""Changes a caller asks for to a parent the engine owns: cancelling or changing one of its legs, cancelling the whole parent, and halting it for flatten."""

import decimal

from unified_broker_interface.utilities.broker_orders.utilities.broker_answer import (
    BrokerAnswer,
)
from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.parent_order import (
    ParentOrder,
)
from unified_broker_interface.utilities.order_engine.utilities.registry import (
    SYNTHETIC_ORDER_CLASSES,
)

CANCEL_LEG = 'cancel_leg'
MODIFY_LEG = 'modify_leg'
CANCEL_PARENT = 'cancel_parent'
MODIFY_HELD = 'modify_held'
HALT_EVERY_PARENT = 'halt'


class ParentCommands:
    """Runs a caller's change to a parent on the worker that owns it, through the parent's own order type.

    `PUT /api/orders/modify` and `DELETE /api/orders/cancel` hand a change to an order the engine placed here rather than sending it themselves, so the order type records it and carries on from it, and the change cannot race the type's own repricing. `DELETE /api/orders/cancel` with `parent_id`, and `DELETE /api/orders/parents`, cancel a whole parent, including one that has placed nothing yet, or with `part` one part of a plan, and flatten halts every open parent before it cancels and closes.

    Attributes:
        placement (EnginePlacement): What an order type uses to reach a broker.
        event_log (SyntheticOrderEventLog): The record.
        parent_store (ParentStore): The Redis copy of the parents.
        logger (logging.Logger): The logger.
        gates (RiskGates | None): The limits.
    """

    def __init__(self, placement, event_log, parent_store, logger, gates):
        """Builds the commands.

        Args:
            placement (EnginePlacement): What an order type uses to reach a broker.
            event_log (SyntheticOrderEventLog): The record.
            parent_store (ParentStore): The Redis copy of the parents.
            logger (logging.Logger): The logger.
            gates (RiskGates | None): The limits.

        Returns:
            None: This method returns nothing.
        """
        self.placement = placement
        self.event_log = event_log
        self.parent_store = parent_store
        self.logger = logger
        self.gates = gates

    def run(self, intent):
        """Runs the command an intent carries.

        Args:
            intent (dict): The intent document, with `command` and the command's arguments in `body`.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 for a command the engine does not know, 404 when the parent or the leg is not known, and 409 when it has already finished.
        """
        command = intent.get('command')
        arguments = intent.get('body') or {}
        if command == CANCEL_LEG:
            return self.cancel_leg(arguments)
        if command == MODIFY_LEG:
            return self.modify_leg(arguments)
        if command == CANCEL_PARENT:
            return self.cancel_parent(arguments)
        if command == MODIFY_HELD:
            return self.modify_held(arguments)
        raise RefusedRequestError.refusal(
            f'the order engine does not run the command {command!r}',
            400,
        )

    def runner_for(self, parent_order_id):
        """The order type for one parent, rebuilt from its Redis record.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            SyntheticOrder: The order type, holding the parent.

        Raises:
            RefusedRequestError: With HTTP 404 when the parent or its type is not known.
        """
        document = self.parent_store.parent(parent_order_id) if parent_order_id else None
        if document is None:
            raise RefusedRequestError.refusal(
                'the order engine holds no parent with this id',
                404,
                parent_id=parent_order_id,
            )
        parent = ParentOrder.from_document(document)
        synthetic_order_class = SYNTHETIC_ORDER_CLASSES.get(parent.synthetic_type)
        if synthetic_order_class is None:
            raise RefusedRequestError.refusal(
                f'the order engine no longer runs {parent.synthetic_type!r} orders',
                404,
                parent_id=parent_order_id,
            )
        return synthetic_order_class(
            parent,
            self.placement,
            self.event_log,
            self.parent_store,
            self.logger,
            self.gates,
        )

    def leg_to_change(self, runner, arguments):
        """The leg a cancel or a change names, which must still be resting at its broker.

        Args:
            runner (SyntheticOrder): The parent's order type.
            arguments (dict): The command's arguments, with `broker` and `order_id`.

        Returns:
            OrderLeg: The leg.

        Raises:
            RefusedRequestError: With HTTP 404 when the parent has no such leg, and 409 when the leg has finished.
        """
        broker = arguments.get('broker')
        order_id = str(arguments.get('order_id'))
        leg = runner.parent.leg_by_broker_order(broker, order_id)
        if leg is None:
            raise RefusedRequestError.refusal(
                'the order engine holds no leg for this order',
                404,
                broker=broker,
                order_id=order_id,
            )
        if leg.is_finished():
            raise RefusedRequestError.refusal(
                f'the order is already {leg.state}',
                409,
                broker=broker,
                order_id=order_id,
            )
        return leg

    def answered(self, runner, leg, outcome, status_message, broker_response):
        """The answer for a cancel or change of one leg, in the shape the routes answer with.

        Args:
            runner (SyntheticOrder): The parent's order type.
            leg (OrderLeg): The leg.
            outcome (str): `accepted`, `rejected` or `unknown`.
            status_message (str | None): Why the outcome is not `accepted`.
            broker_response (object | None): The broker's body.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        return {
            'broker': leg.broker,
            'order_id': leg.broker_order_id,
            'outcome': outcome,
            'status_message': status_message,
            'broker_response': broker_response,
            'parent_id': runner.parent.parent_order_id,
            'synthetic_type': runner.parent.synthetic_type,
        }, BrokerAnswer.OUTCOME_STATUSES.get(outcome, 504)

    def cancel_leg(self, arguments):
        """Cancels one leg of a parent through its order type.

        Args:
            arguments (dict): `parent_id`, `broker` and `order_id`.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        runner = self.runner_for(arguments.get('parent_id'))
        leg = self.leg_to_change(runner, arguments)
        outcome, status_message, broker_response = runner.cancel_leg_answered(
            leg,
            'cancelled through DELETE /api/orders/cancel',
        )
        if outcome == 'accepted':
            runner.take_caller_cancel(leg)
        runner.save()
        return self.answered(runner, leg, outcome, status_message, broker_response)

    def modify_leg(self, arguments):
        """Changes one leg of a parent through its order type, which then carries on from the new values.

        Args:
            arguments (dict): `parent_id`, `broker`, `order_id`, and any of `quantity` (in the broker's own terms), `quantity_units` (as the caller gave it), `price` and `trigger_price`.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        runner = self.runner_for(arguments.get('parent_id'))
        leg = self.leg_to_change(runner, arguments)
        problem = runner.outside_change_problem(
            leg,
            arguments.get('quantity_units'),
        )
        if problem is not None:
            raise RefusedRequestError.refusal(
                problem,
                409,
                broker=leg.broker,
                order_id=leg.broker_order_id,
            )
        quantity = arguments.get('quantity')
        price = self.decimal_or_none(arguments.get('price'))
        trigger_price = self.decimal_or_none(arguments.get('trigger_price'))
        outcome, status_message, broker_response = runner.apply_outside_modification(
            leg,
            quantity,
            price,
            trigger_price,
            arguments.get('quantity_units'),
        )
        runner.save()
        return self.answered(runner, leg, outcome, status_message, broker_response)

    def cancel_parent(self, arguments):
        """Cancels a whole parent: every leg still resting at a broker, and the parent itself; or, when `part` names one, only that part of a plan.

        Args:
            arguments (dict): `parent_id`, and optionally `part` and `dry_run`.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int): 200 once the parent is cancelled, or for a dry run, and 207 when a leg's cancel was refused or unknown, which leaves the parent `cancelling` until that leg finishes.

        Raises:
            RefusedRequestError: With HTTP 404 when the plan has no such part, and 409 when the parent or the part has already finished, or a part is named on an order that is not a plan.
        """
        runner = self.runner_for(arguments.get('parent_id'))
        dry_run = arguments.get('dry_run') is True
        if arguments.get('part') is not None:
            return runner.cancel_part(arguments['part'], dry_run)
        if runner.parent.is_terminal():
            raise RefusedRequestError.refusal(
                f'the parent is already {runner.parent.state}',
                409,
                parent_id=runner.parent.parent_order_id,
            )
        if dry_run:
            return self.cancel_parent_dry_run(runner)
        cancelled_legs = runner.cancel_by_caller(
            'cancelled by the caller',
        )
        status = 200
        if runner.parent.state == 'cancelling':
            status = 207
        return {
            'parent_id': runner.parent.parent_order_id,
            'synthetic_type': runner.parent.synthetic_type,
            'state': runner.parent.state,
            'cancelled_legs': cancelled_legs,
        }, status

    def cancel_parent_dry_run(self, runner):
        """The answer to a dry run of cancelling a whole parent: the legs a cancel would be sent for, with nothing sent or changed.

        Args:
            runner (SyntheticOrder): The parent's order type.

        Returns:
            tuple: The answer's body (dict) and the HTTP status 200.
        """
        resting_legs = []
        for leg in runner.parent.legs:
            if leg.is_finished() or not leg.broker_order_id:
                continue
            resting_legs.append({
                'leg_id': leg.leg_id,
                'broker': leg.broker,
                'order_id': leg.broker_order_id,
            })
        return {
            'parent_id': runner.parent.parent_order_id,
            'synthetic_type': runner.parent.synthetic_type,
            'state': runner.parent.state,
            'resting_legs': resting_legs,
            'dry_run': True,
            'status_message': 'the cancel is valid; nothing was cancelled',
        }, 200

    def modify_held(self, arguments):
        """Changes an order the engine is still holding, such as a virtual limit order, or, when `part` names one, a part of a plan that has not yet been sent.

        Args:
            arguments (dict): `parent_id`, any of `price` and `quantity` (in units), with `dry_run`, and optionally `part` with `trigger_price`.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 404 when the parent or the part is not known, and 409 when it holds nothing that can be changed.
        """
        runner = self.runner_for(arguments.get('parent_id'))
        quantity = arguments.get('quantity')
        if quantity is not None:
            quantity = int(quantity)
        dry_run = arguments.get('dry_run') is True
        if arguments.get('part') is not None:
            return runner.modify_part(
                arguments['part'],
                self.decimal_or_none(arguments.get('price')),
                self.decimal_or_none(arguments.get('trigger_price')),
                quantity,
                dry_run,
            )
        return runner.modify_held(
            self.decimal_or_none(arguments.get('price')),
            quantity,
            dry_run,
        )

    def halt(self, parent_order_id):
        """Stops one open parent from acting again, leaving its legs to flatten.

        Args:
            parent_order_id (str): The parent's id.

        Returns:
            None: This method returns nothing.
        """
        try:
            runner = self.runner_for(parent_order_id)
        except RefusedRequestError:
            return
        runner.stop_acting('halted by POST /api/orders/flatten')

    def decimal_or_none(self, value):
        """A price as a decimal, or None when none was given.

        Args:
            value (object): The price as the command carried it.

        Returns:
            decimal.Decimal | None: The price.
        """
        if value is None:
            return None
        return decimal.Decimal(str(value))
