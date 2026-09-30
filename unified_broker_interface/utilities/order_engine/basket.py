"""Several orders on several instruments, sent together and reported together."""

from unified_broker_interface.utilities.broker_selection.utilities.order_legs import (
    OrderLegs,
)
from unified_broker_interface.utilities.order_engine.base import SyntheticOrder
from unified_broker_interface.utilities.order_engine.utilities.candidate_legs import (
    CandidateLegs,
)


class Basket(SyntheticOrder):
    """A list of orders on different instruments, placed in one request and answered in one answer.

    Buy the whole of a model portfolio. Put on all four legs of an iron condor. Roll a position by closing this month and opening next. Each of those is several orders that belong together, and sending them as separate HTTP requests means several round trips, several answers to correlate by hand, and no single thing to point at afterwards when asking what happened.

    **It is not all-or-nothing, and no basket anywhere is.** Brokers sell basket orders as a convenience and this is the same convenience: each leg is an ordinary order that can be accepted, rejected or left unknown on its own. What this adds over five separate requests is that the five are one parent, so one identifier finds all of them, one event log records them in order, and the answer says plainly which of them got through.

    That last part is the part worth having. A four-legged options strategy where the third leg was rejected is not three quarters of a strategy — it is an unhedged short somebody has to find out about quickly. The answer lists every leg's outcome rather than reporting a single verdict, and the parent goes to `failed` rather than `working` when any leg's fate is unknown, because a human has to look at that.

    Legs go out in the order they were given, and that order is the caller's to choose. It matters for Indian futures and options margin: buying the hedge before selling the short leg gets the spread's margin benefit, where the other order briefly demands the full margin for a naked short and can be rejected for it.

    **Every leg goes to the broker the first one chose**, rather than being spread across brokers as separate orders would be. Margin offsets exist inside one account and nowhere else, so an iron condor with two legs at one broker and two at another is charged as four naked positions rather than as a defined-risk strategy, and may simply be refused for want of margin. Spreading the legs would use the rate budget better and would be wrong for the reason people send baskets in the first place.

    Because the first leg chooses for all of them, it hands the whole list to the placement, so the lowest-cost selector checks that the broker it picks can afford the whole basket, at the highest point it reaches as the legs go out in the given order. With `"hedge_benefit": true` in the `synthetic` object, options and futures on one underlying and expiry are priced as a hedged whole at the brokers known to allow that, which for a defined-risk strategy such as an iron condor is often less than half of the legs added up.
    """

    SYNTHETIC_TYPE = 'basket'
    FINISHES_WITH_LEGS = True

    def run(self, intent, started_at):
        """Places every candidate and answers with what each one did.

        Args:
            intent (dict): The intent document.
            started_at (float): `time.perf_counter()` when the engine took the intent.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).

        Raises:
            RefusedRequestError: With HTTP 400 when the candidates cannot be read.
        """
        order = self.read_order(self.parent.body)
        candidates = CandidateLegs().read(
            self.parent.parameters,
            self.parent.body,
        )
        orders = [
            (instrument_id, self.read_order(body))
            for instrument_id, body in candidates
        ]
        legs = OrderLegs(
            orders,
            self.parent.parameters.get('hedge_benefit') is True,
        )

        if order.dry_run:
            prepared = self.placement.prepare(
                orders[0][1],
                orders[0][0],
                None,
                legs,
            )
            return self.placement.dry_run_answer(prepared, started_at)

        self.record_received()
        self.save()

        answers = []
        for instrument_id, candidate_order in orders:
            broker_name = self.chosen_broker()
            leg_group = None
            if broker_name is None:
                leg_group = legs
            body, status, _ = self.place_leg(
                'basket',
                candidate_order,
                started_at,
                broker_name,
                instrument_id,
                leg_group,
            )
            answers.append((instrument_id, body, status))
        return self.settle(answers)

    def settle(self, answers):
        """Records what the basket did and answers the waiting worker.

        Args:
            answers (list): One `(instrument_id, body, status)` per leg.

        Returns:
            tuple: The answer's body (dict) and its HTTP status (int).
        """
        outcomes = [body.get('outcome') for _, body, _ in answers]
        if 'unknown' in outcomes:
            state = 'failed'
        elif 'accepted' in outcomes:
            state = 'working'
        else:
            state = 'rejected'
        placed = sum(1 for outcome in outcomes if outcome == 'accepted')
        self.record_state(
            state,
            f'{placed} of {len(answers)} legs were accepted',
        )
        self.save()

        outcome, status = self.combined_answer(
            outcomes,
            [status for _, _, status in answers],
        )
        return {
            'broker': None,
            'instrument_id': self.parent.instrument_id,
            'parent_id': self.parent.parent_order_id,
            'tag': self.parent.tag,
            'outcome': outcome,
            'legs': [
                {
                    'instrument_id': instrument_id,
                    'broker': body.get('broker'),
                    'order_id': body.get('order_id'),
                    'outcome': body.get('outcome'),
                    'status_message': body.get('status_message'),
                }
                for instrument_id, body, _ in answers
            ],
            'skipped': answers[0][1].get('skipped') if answers else [],
            'timing_ms': answers[0][1].get('timing_ms') if answers else {},
        }, status
