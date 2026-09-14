"""
Flattrade ticks. Flattrade runs on Noren, so everything is `NorenTickNormalizer`.
"""

from stock_brokers.instruments.ticks.noren import NorenTickNormalizer

class FlattradeTickNormalizer(NorenTickNormalizer):
    """
    Normalizes Flattrade ticks.
    """

    BROKER_NAME = "flattrade"
