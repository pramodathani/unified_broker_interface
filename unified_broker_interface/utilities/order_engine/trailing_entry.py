"""A stop entry that follows the market down, so the first real bounce takes the trade."""

from unified_broker_interface.utilities.order_engine.utilities.trailing import (
    TrailingOrder,
)


class TrailingEntry(TrailingOrder):
    """An entry that waits for the fall to stop rather than guessing where it stops.

    `transaction_type` is the side you want to end up on, and the stop is on that same side. A buy sits above the market and is lowered as the market falls.

    The problem it solves is the one every buyer of a falling market has. You think it is cheap at 1000, so you bid there, and it trades at 980. You think it is cheap at 980, and it trades at 960. A trailing entry says instead: I do not know where the bottom is, but I will buy the first bounce of ten rupees off whatever the bottom turns out to be. The trigger follows the low down — 1010, then 990, then 970 — and the first time the price comes back up through it, the order fires.

    It is the exact mirror of a trailing stop, and it is the same object in the code, which is worth stating plainly because the two sound like different things. A trailing stop is a sell stop ratcheting up behind a rising market. A trailing entry to buy is a buy stop ratcheting down behind a falling one. The direction is decided by the side of the stop and nothing else.

    A buy stop's trigger sits above the last price, which is the direction Indian brokers allow a native stop to be placed in, so this one rests at the exchange like any other stop entry and fires at exchange speed.
    """

    SYNTHETIC_TYPE = 'trailing_entry'
    ARMED_STATE = 'working'

    def leg_side(self, transaction_type):
        """The side the caller wants to end up on, which is the side the stop trades.

        Args:
            transaction_type (str): The side the caller asked for.

        Returns:
            str: The same side.
        """
        return transaction_type
