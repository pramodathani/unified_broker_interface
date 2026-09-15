"""
The brokers whose ticks the unified service can normalize, and their normalizers.

A broker is added here with its normalizer and offline tests. Being here is not the same as being
trusted: ownership prefers the brokers in `sources.VERIFIED_BROKERS`, which a broker joins only after
its normalizer has been checked against a live session, and uses the others only for instruments no
verified broker streams. Ticks from a broker with no normalizer are counted and ignored.
"""

from stock_brokers.instruments.ticks.dhan import DhanTickNormalizer
from stock_brokers.instruments.ticks.flattrade import FlattradeTickNormalizer
from stock_brokers.instruments.ticks.fyers import FyersTickNormalizer
from stock_brokers.instruments.ticks.groww import GrowwTickNormalizer
from stock_brokers.instruments.ticks.indmoney import IndmoneyTickNormalizer
from stock_brokers.instruments.ticks.kotak import KotakTickNormalizer
from stock_brokers.instruments.ticks.shoonya import ShoonyaTickNormalizer
from stock_brokers.instruments.ticks.stoxkart import StoxkartTickNormalizer
from stock_brokers.instruments.ticks.wisdom_capital import WisdomCapitalTickNormalizer
from stock_brokers.instruments.ticks.zerodha import ZerodhaTickNormalizer

NORMALIZERS = {
    "zerodha": ZerodhaTickNormalizer,
    "dhan": DhanTickNormalizer,
    "kotak": KotakTickNormalizer,
    "flattrade": FlattradeTickNormalizer,
    "shoonya": ShoonyaTickNormalizer,
    "fyers": FyersTickNormalizer,
    "wisdom_capital": WisdomCapitalTickNormalizer,
    "groww": GrowwTickNormalizer,
    "indmoney": IndmoneyTickNormalizer,
    "stoxkart": StoxkartTickNormalizer,
}

def build_normalizers(brokers=None):
    """
    One normalizer per broker.

    Args:
        brokers (list[str] | None): Broker names to build for, or None for every broker with a normalizer.

    Returns:
        dict: Broker name to its TickNormalizer instance.

    Raises:
        ValueError: If a named broker has no normalizer.
    """
    names = list(NORMALIZERS) if brokers is None else list(brokers)
    unknown = [name for name in names if name not in NORMALIZERS]
    if unknown:
        raise ValueError(f"no tick normalizer for: {', '.join(unknown)}")
    return {name: NORMALIZERS[name]() for name in names}
