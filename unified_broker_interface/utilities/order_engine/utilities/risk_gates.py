"""The limits every order the engine sends has to pass, in one place."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)
from unified_broker_interface.utilities.order_engine.utilities.repricing_throttle import (
    RepricingThrottle,
)


class RiskGates:
    """The rate budget, the daily loss lockout, the order-to-trade ratio, the re-pricing throttle and the daily order count, held together.

    They are one object rather than four arguments because every order passes all of them and a new one should be added in one place rather than threaded through every caller.

    This is the reason the order engine exists rather than a simpler design. A limit written into a gunicorn worker is enforced once per worker, which is to say enforced twice and therefore not at all; a limit here is enforced once, because exactly one engine runs and nothing else in engine mode sends a placement.

    That claim has one honest hole in it, recorded here rather than left to be discovered: `PUT /api/orders/modify` and `DELETE /api/orders/cancel` still go straight from an API worker to a broker. They count towards an exchange's order rate too. Until they are routed through the engine, these are limits on placements.

    Attributes:
        rate_budget (RateBudget): How fast orders may be sent.
        loss_lockout (LossLockout): Whether the day has lost too much to place another.
        ratio (OrderToTradeRatio): How many orders are sent for each that trades.
        throttle (RepricingThrottle): How often any one resting order may be moved.
        daily_count (DailyOrderCount | None): How many orders each broker has been sent today against its cap, or None when no broker is capped.
    """

    def __init__(
        self,
        rate_budget,
        loss_lockout,
        ratio,
        throttle=None,
        daily_count=None,
    ):
        """Builds the gates.

        Args:
            rate_budget (RateBudget): How fast orders may be sent.
            loss_lockout (LossLockout): Whether the day has lost too much.
            ratio (OrderToTradeRatio): How many orders are sent for each that trades.
            throttle (RepricingThrottle | None): How often one order may be moved, or None for a throttle that allows every move.
            daily_count (DailyOrderCount | None): The daily order count, or None when no broker is capped.

        Returns:
            None: This method returns nothing.
        """
        self.rate_budget = rate_budget
        self.loss_lockout = loss_lockout
        self.ratio = ratio
        self.throttle = throttle if throttle is not None else RepricingThrottle(0)
        self.daily_count = daily_count

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

    def refuse_if_capped(self, broker_name, closes_position):
        """Refuses one order when its broker is too close to the day's order cap.

        This runs once the broker is known and before anything is recorded, so an order refused here leaves no leg behind.

        Args:
            broker_name (str): The broker the order would go to.
            closes_position (bool): Whether the order closes a position, which may use the part of the cap kept for exits.

        Returns:
            None: This method returns nothing.

        Raises:
            RefusedRequestError: With HTTP 429 when the broker has no room left today for this kind of order.
        """
        if self.daily_count is None:
            return
        self.daily_count.refuse_if_capped(broker_name, closes_position)

    def count_sent(self, broker_name):
        """Counts one order sent, for the order-to-trade ratio and the daily order count.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.ratio.count_sent(broker_name)
        if self.daily_count is not None:
            self.daily_count.count_sent(broker_name)

    def count_traded(self, broker_name):
        """Counts one order that traded, for the order-to-trade ratio.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.ratio.count_traded(broker_name)

    def allow_reprice(self, leg_id):
        """Whether one resting order may be moved again yet.

        This refuses rather than waits, which is the opposite of what the rate budget does, and the difference is deliberate. An order held back by the budget is one the system could not send yet and will want to send in a moment, unchanged. An order held back by the throttle wants to be moved to wherever the market is at the time it is finally sent, and a price worked out a second earlier is the wrong price. So it is dropped, and the next tick works out a fresh one.

        Args:
            leg_id (str): The leg being moved.

        Returns:
            bool: True when the move may be sent.
        """
        return self.throttle.allows(leg_id)

    def record_reprice(self, leg_id):
        """Remembers that one resting order has just been moved.

        Args:
            leg_id (str): The leg that moved.

        Returns:
            None: This method returns nothing.
        """
        self.throttle.record(leg_id)

    def counts(self):
        """What every gate has done, for the engine's shutdown line.

        Returns:
            dict: `rate`, `locked_out`, `order_to_trade` and `repricing`, and `daily_count` when a broker is capped.
        """
        counts = {
            'rate': self.rate_budget.counts(),
            'locked_out': self.loss_lockout.locked_out,
            'order_to_trade': self.ratio.counts(),
            'repricing': self.throttle.counts(),
        }
        if self.daily_count is not None:
            counts['daily_count'] = self.daily_count.counts()
        return counts
