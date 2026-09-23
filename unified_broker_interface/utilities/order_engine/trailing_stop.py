"""A stop on a position you hold, that follows the market as the trade goes your way."""

from unified_broker_interface.utilities.order_engine.utilities.trailing import (
    TrailingOrder,
)


class TrailingStop(TrailingOrder):
    """A stop that locks in a move without giving the trade a ceiling.

    `transaction_type` is the side that **opened** the position, as it is for every type that protects one, so a long is protected by asking for a BUY and the stop this places is a sell.

    The idea is older than electronic trading. You are long at 1000 with a stop at 990. The price goes to 1020, and the ten rupees you were risking are now ten rupees you would be giving back, so you move the stop to 1010. The price goes to 1040 and the stop goes to 1030. It never comes back down, so a pullback to 1015 leaves it at 1030 and the trade is stopped out having kept most of the move rather than all of the risk.

    That last sentence is the whole type. A stop that followed the price back down would never fire at all, and nothing about it would be obviously wrong until a day when it mattered.

    `trail_points` follows at a fixed distance and `trail_percent` at a proportional one. The percentage is measured against the high-water mark rather than against the entry, so the distance widens as the trade goes further, which is what somebody asking for a percentage usually means: risk a tenth of the position's value, not a tenth of what it was worth when you bought it.

    The Noren bracket and cover products have a native trailing field, so a broker could in principle do all of this. Flattrade's API restricts both products, which is why it is here.
    """

    SYNTHETIC_TYPE = 'trailing_stop'
    ARMED_STATE = 'protecting'

    def leg_side(self, transaction_type):
        """The side that closes the position, which is the side the stop trades.

        Args:
            transaction_type (str): The side that opened the position.

        Returns:
            str: BUY to protect a short, SELL to protect a long.
        """
        return 'SELL' if transaction_type == 'BUY' else 'BUY'
