"""Reading the several orders a multi-instrument parent is made of."""

from unified_broker_interface.utilities.broker_orders.utilities.refused_request import (
    RefusedRequestError,
)

MOST_CANDIDATES = 25


class CandidateLegs:
    """Turns a list of `candidates` into the orders a basket, an OCA group or a spread sends.

    Every type in this package until now has traded one instrument, because the REST route resolves the instrument before the engine sees the intent and writes one id into the parent. A basket, a spread and a one-cancels-all group all need several, and there is nowhere in that route for a second one to come from.

    So a candidate names its instrument by id outright. That is a real cost — the caller has to have looked the ids up, where a single order can be asked for by exchange and symbol — and it is the honest boundary. Resolving an identity is a rule about ambiguity, near matches and expiries that lives in one place in the REST layer, and duplicating a second copy of it inside the engine so that a basket can say "RELIANCE" is how two answers to the same question start to disagree.

    An instrument id is not a hardship in practice. The unified catalogue is keyed by it, every order answer carries it back, and anything assembling a basket of five instruments has already looked all five up to decide it wanted them.

    A candidate carries only what differs from the order the caller sent. The side, the product, the validity and the order type are taken from the parent's own body unless the candidate overrides them, so a basket of five stocks bought the same way is five instrument ids and five quantities.
    """

    def read(self, parameters, body):
        """The candidates, as bodies ready to be validated.

        Args:
            parameters (dict): The caller's `synthetic` object.
            body (dict): The caller's request body, which every candidate starts from.

        Returns:
            list: One `(instrument_id, body)` per candidate, in the order they were given.

        Raises:
            RefusedRequestError: With HTTP 400 when there are no candidates, too many, or one of them is not a dictionary naming an instrument.
        """
        given = parameters.get('candidates')
        if not isinstance(given, list) or not given:
            raise RefusedRequestError.refusal(
                'this order type needs candidates, a list of the orders it is '
                'made of, each naming its instrument_id',
                400,
            )
        if len(given) > MOST_CANDIDATES:
            raise RefusedRequestError.refusal(
                f'this order type takes at most {MOST_CANDIDATES} candidates, '
                f'not {len(given)}',
                400,
            )
        candidates = []
        seen = set()
        for position, candidate in enumerate(given):
            candidates.append(
                self.one(candidate, body, position, seen),
            )
        return candidates

    def one(self, candidate, body, position, seen):
        """One candidate, as a body ready to be validated.

        Args:
            candidate (object): The candidate as the caller wrote it.
            body (dict): The caller's request body.
            position (int): Which candidate this is, for the message.
            seen (set): The instrument ids already used, which this adds to.

        Returns:
            tuple: The instrument id (str) and the body (dict).

        Raises:
            RefusedRequestError: With HTTP 400 when the candidate is not a dictionary, names no instrument, or repeats one.
        """
        if not isinstance(candidate, dict):
            raise RefusedRequestError.refusal(
                f'candidate {position + 1} must be an object, not '
                f'{type(candidate).__name__}',
                400,
            )
        instrument_id = candidate.get('instrument_id')
        if not instrument_id:
            raise RefusedRequestError.refusal(
                f'candidate {position + 1} must name its instrument_id',
                400,
            )
        if instrument_id in seen:
            raise RefusedRequestError.refusal(
                f'candidate {position + 1} repeats instrument {instrument_id}, '
                'and two orders on one instrument in the same group cannot be '
                'told apart afterwards',
                400,
            )
        seen.add(instrument_id)
        wanted = dict(body)
        wanted.pop('price_reference', None)
        wanted.pop('quantity_reference', None)
        wanted.pop('synthetic', None)
        for name in (
            'transaction_type',
            'product',
            'order_type',
            'validity',
            'quantity',
            'price',
            'trigger_price',
            'tag',
        ):
            if name in candidate:
                wanted[name] = candidate[name]
        return instrument_id, wanted
