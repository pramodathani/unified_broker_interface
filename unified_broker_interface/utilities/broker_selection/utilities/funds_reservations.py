"""Margin promised to orders this process has just sent a broker, until the broker's funds show it."""

import datetime
import decimal
import threading

ZERO = decimal.Decimal(0)


class FundsReservations:
    """A ledger of margin this process has promised each broker's recent orders, held in memory.

    A broker's free cash is read every half second, so a burst of ten orders arriving together would all see the same balance and could all be sent to a broker that can afford only one of them. Each order chosen for a broker therefore reserves its margin here, and the funds check subtracts what is reserved.

    A reservation is dropped once the broker's funds were read more than `settle_seconds` after it was made, because by then the balance already reflects the order, or the order was refused and never used the money. That needs no answer from the broker and no timer.

    Attributes:
        settle_seconds (float): How long after a reservation a funds reading is trusted to include it.
        reservations (dict): For each broker, a list of `(moment, amount)` tuples, where `moment` is a naive local `datetime.datetime` and `amount` a `decimal.Decimal`.
        lock (threading.Lock): Guards `reservations`, which several threads update.
    """

    def __init__(self, settle_seconds):
        """Builds an empty ledger.

        Args:
            settle_seconds (float): How long after a reservation a funds reading is trusted to include it.

        Returns:
            None: This method returns nothing.
        """
        self.settle_seconds = settle_seconds
        self.reservations = {}
        self.lock = threading.Lock()

    def reserve(self, broker_name, amount, now=None):
        """Records margin promised to an order just chosen for a broker.

        Args:
            broker_name (str): The broker.
            amount (decimal.Decimal): The margin.
            now (datetime.datetime | None): The moment, as naive local time, or None for now.

        Returns:
            None: This method returns nothing.
        """
        now = now or datetime.datetime.now()
        with self.lock:
            entries = self.reservations.get(broker_name)
            if entries is None:
                entries = []
                self.reservations[broker_name] = entries
            entries.append((now, amount))

    def reserved(self, broker_name, funds_read_at):
        """The margin still promised at a broker that its latest funds reading does not yet show.

        Args:
            broker_name (str): The broker.
            funds_read_at (datetime.datetime | None): When the broker's funds were read, as naive local time, or None when not known, which keeps every reservation.

        Returns:
            decimal.Decimal: The sum of the reservations still held.
        """
        settle = datetime.timedelta(seconds=self.settle_seconds)
        with self.lock:
            entries = self.reservations.get(broker_name)
            if not entries:
                return ZERO
            kept = []
            for moment, amount in entries:
                if funds_read_at is None or moment + settle > funds_read_at:
                    kept.append((moment, amount))
            self.reservations[broker_name] = kept
            total = ZERO
            for moment, amount in kept:
                total = total + amount
        return total
