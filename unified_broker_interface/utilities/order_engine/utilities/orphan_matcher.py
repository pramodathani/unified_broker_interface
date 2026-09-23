"""Deciding whether an order left at a broker by a crash belongs to a parent, and refusing to guess."""

import datetime

STALE_BOOK_SECONDS = 60.0
TIMESTAMP_TOLERANCE_SECONDS = 2.0
PRICE_PLACES = 4


class OrphanMatcher:
    """Tries to attribute an order the engine may have sent but never heard the answer to.

    The engine records a leg and commits before sending it, so a crash in between leaves a leg in `sending` with no broker order id, and possibly a live order at the broker. Because the caller's own tag is sent unchanged on an entry leg, that order carries nothing naming its parent, and only the order's own fields can identify it.

    This class is deliberately unwilling. It attributes an order only when exactly one unclaimed order in the broker's book matches every field the engine sent, within a few seconds of when it sent it. Zero matches and two matches both end the same way: the parent is parked in `failed` for a person to look at. Attributing the wrong order would hang a stop and a target on a position the engine does not own, which is worse in every way than admitting it does not know.

    Attributes:
        logger (logging.Logger): The logger.
    """

    def __init__(self, logger):
        """Builds the matcher.

        Args:
            logger (logging.Logger): The logger.

        Returns:
            None: This method returns nothing.
        """
        self.logger = logger

    def attribute(self, leg, book, polled_at, claimed_order_ids, now=None):
        """Decides what one leg left in `sending` should become.

        Args:
            leg (OrderLeg): The leg found in `sending`.
            book (dict): That broker's `<broker>:orders:orders` entries, by the broker's order id.
            polled_at (float | None): When that broker's book was last read, as an epoch.
            claimed_order_ids (set): Broker order ids already belonging to a leg, which are never candidates.
            now (float | None): The moment to reckon staleness from, or None for now.

        Returns:
            dict: `{outcome, status_message, broker_order_id, candidates}`, where `outcome` is `attributed` or `abandoned`.
        """
        now = now if now is not None else datetime.datetime.now(
            datetime.timezone.utc,
        ).timestamp()
        if not self.book_is_fresh(polled_at, now):
            return self.abandoned(
                'the broker book was too old to attribute this order, so it '
                'may be live and unprotected',
                [],
            )

        candidates = self.candidates(leg, book, claimed_order_ids)
        if len(candidates) == 1:
            return {
                'outcome': 'attributed',
                'status_message': (
                    'exactly one unclaimed order at the broker matches what '
                    'was sent'
                ),
                'broker_order_id': candidates[0],
                'candidates': candidates,
            }
        if not candidates:
            return self.abandoned(
                'no order at the broker matches what was sent, so this order '
                'was probably never placed, but that is not certain',
                candidates,
            )
        return self.abandoned(
            'more than one order at the broker matches what was sent, so '
            'attributing one of them would be a guess',
            candidates,
        )

    def abandoned(self, status_message, candidates):
        """The answer when the leg cannot be attributed.

        Args:
            status_message (str): Why.
            candidates (list): The broker order ids considered.

        Returns:
            dict: The outcome.
        """
        return {
            'outcome': 'abandoned',
            'status_message': status_message,
            'broker_order_id': None,
            'candidates': candidates,
        }

    def book_is_fresh(self, polled_at, now):
        """Whether the broker's book was read recently enough to be worth comparing.

        A book that has not been read for a minute makes every leg look orphaned, because the order the engine sent may simply not be in it yet. Attributing nothing is then the wrong answer for the wrong reason, so the matcher does not run at all.

        Args:
            polled_at (float | None): When the book was last read, as an epoch.
            now (float): The moment to reckon from.

        Returns:
            bool: True when the book is fresh enough.
        """
        if polled_at is None:
            return False
        return (now - polled_at) <= STALE_BOOK_SECONDS

    def candidates(self, leg, book, claimed_order_ids):
        """Every unclaimed order in the book that matches what the engine sent.

        Args:
            leg (OrderLeg): The leg found in `sending`.
            book (dict): That broker's order book entries, by the broker's order id.
            claimed_order_ids (set): Broker order ids already belonging to a leg.

        Returns:
            list: The matching broker order ids, sorted.
        """
        matched = []
        for broker_order_id, entry in book.items():
            if broker_order_id in claimed_order_ids:
                continue
            order = (entry or {}).get('order')
            if not isinstance(order, dict):
                continue
            if self.matches(leg, order):
                matched.append(broker_order_id)
        return sorted(matched)

    def matches(self, leg, order):
        """Whether one order in the book could be the one this leg sent.

        Every field the engine chose has to agree, including the tag, and both being absent counts as agreeing. The order's own timestamp has to fall inside the window the request was in flight, widened by a couple of seconds for the clocks to disagree.

        Args:
            leg (OrderLeg): The leg found in `sending`.
            order (dict): One order from the broker's book, on the order contract.

        Returns:
            bool: True when every compared field agrees.
        """
        if not self.identifier_agrees(leg, order):
            return False
        for attribute, field in (
            ('transaction_type', 'transaction_type'),
            ('product', 'product'),
            ('order_type', 'order_type'),
            ('validity', 'validity'),
            ('tag_sent', 'tag'),
        ):
            if self.text(getattr(leg, attribute)) != self.text(order.get(field)):
                return False
        if self.whole(leg.quantity) != self.whole(order.get('quantity')):
            return False
        for attribute, field in (
            ('price', 'price'),
            ('trigger_price', 'trigger_price'),
        ):
            if self.rounded(getattr(leg, attribute)) != self.rounded(
                order.get(field),
            ):
                return False
        return self.timestamp_agrees(leg, order)

    def identifier_agrees(self, leg, order):
        """Whether the order names the instrument the request named.

        A broker's book reports the instrument under whichever of the two fields that broker uses, so both are compared and either matching is enough.

        Args:
            leg (OrderLeg): The leg.
            order (dict): The order from the book.

        Returns:
            bool: True when the identifier the request sent appears in the order.
        """
        identifier = self.text(leg.identifier_sent)
        if identifier is None:
            return False
        return identifier in (
            self.text(order.get('instrument_token')),
            self.text(order.get('tradingsymbol')),
        )

    def timestamp_agrees(self, leg, order):
        """Whether the order was placed while this leg's request was in flight.

        An order in the book without a readable timestamp is accepted rather than refused, because a broker that reports no time should not by itself make an order unattributable; the other fields still have to agree.

        Args:
            leg (OrderLeg): The leg.
            order (dict): The order from the book.

        Returns:
            bool: True when the times are close enough, or the order carries none.
        """
        requested_at = self.moment(leg.requested_at)
        order_at = self.moment(order.get('order_timestamp'))
        if requested_at is None or order_at is None:
            return True
        earliest = requested_at - TIMESTAMP_TOLERANCE_SECONDS
        latest = requested_at + TIMESTAMP_TOLERANCE_SECONDS + 30.0
        return earliest <= order_at <= latest

    def moment(self, value):
        """An ISO timestamp as an epoch, or None.

        Args:
            value (str | None): The timestamp.

        Returns:
            float | None: The epoch.
        """
        if not value:
            return None
        try:
            parsed = datetime.datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.timestamp()

    def text(self, value):
        """A value as text, or None when it is absent or empty.

        Args:
            value (object): The value.

        Returns:
            str | None: The text.
        """
        if value is None or value == '':
            return None
        return str(value)

    def whole(self, value):
        """A quantity as an integer, or None.

        Args:
            value (object): The value.

        Returns:
            int | None: The quantity.
        """
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def rounded(self, value):
        """A price rounded to the places the comparison uses, or None.

        Args:
            value (object): The value.

        Returns:
            float | None: The price.
        """
        if value is None:
            return None
        try:
            return round(float(value), PRICE_PLACES)
        except (TypeError, ValueError):
            return None
