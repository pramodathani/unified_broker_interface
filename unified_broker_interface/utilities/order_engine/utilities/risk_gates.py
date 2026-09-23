"""The limits every order the engine sends has to pass, in one place."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)


class RiskGates:
    """The rate budget, the daily loss lockout and the order-to-trade ratio, held together.

    They are one object rather than three arguments because every order passes all of them and a new one should be added in one place rather than threaded through every caller.

    This is the reason the order engine exists rather than a simpler design. A limit written into a gunicorn worker is enforced once per worker, which is to say enforced twice and therefore not at all; a limit here is enforced once, because exactly one engine runs and nothing else in engine mode sends a placement.

    That claim has one honest hole in it, recorded here rather than left to be discovered: `PUT /api/orders/modify` and `DELETE /api/orders/cancel` still go straight from an API worker to a broker. They count towards an exchange's order rate too. Until they are routed through the engine, these are limits on placements.

    Attributes:
        rate_budget (RateBudget): How fast orders may be sent.
        loss_lockout (LossLockout): Whether the day has lost too much to place another.
        ratio (OrderToTradeRatio): How many orders are sent for each that trades.
    """

    def __init__(self, rate_budget, loss_lockout, ratio):
        """Builds the gates.

        Args:
            rate_budget (RateBudget): How fast orders may be sent.
            loss_lockout (LossLockout): Whether the day has lost too much.
            ratio (OrderToTradeRatio): How many orders are sent for each that trades.

        Returns:
            None: This method returns nothing.
        """
        self.rate_budget = rate_budget
        self.loss_lockout = loss_lockout
        self.ratio = ratio

    def check_before_accepting(self, intent):
        """Refuses an order before any work is done on it, when the day is already locked out.

        This runs before the parent is created, so an order refused here leaves nothing behind. The loss lockout is the only gate that belongs this early: whether the day may trade at all does not depend on which broker the order would go to.

        Args:
            intent (dict): The intent document.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 403 when the day's loss limit has been reached, because the order is understood and refused rather than being something the engine could not do.
        """
        reason = self.loss_lockout.refusal_reason()
        if reason is not None:
            raise RefusedRequestError.refusal(
                reason,
                403,
                intent_id=intent.get('intent_id'),
            )

    def take_rate_token(self, broker_name):
        """Waits for the rate budget to allow one order to a broker.

        Args:
            broker_name (str): The broker the order is going to.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 503 when no token arrived in time, since the order could be placed later but not now.
        """
        if self.rate_budget.take(broker_name):
            return
        raise RefusedRequestError.refusal(
            'the order rate budget is full, so this order was not sent; try '
            'again in a moment',
            503,
            broker=broker_name,
        )

    def count_sent(self, broker_name):
        """Counts one order sent, for the order-to-trade ratio.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.ratio.count_sent(broker_name)

    def count_traded(self, broker_name):
        """Counts one order that traded, for the order-to-trade ratio.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.ratio.count_traded(broker_name)

    def counts(self):
        """What every gate has done, for the engine's shutdown line.

        Returns:
            dict: `rate`, `locked_out` and `order_to_trade`.
        """
        return {
            'rate': self.rate_budget.counts(),
            'locked_out': self.loss_lockout.locked_out,
            'order_to_trade': self.ratio.counts(),
        }
