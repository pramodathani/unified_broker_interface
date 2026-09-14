"""
Shoonya ticks. Shoonya is Finvasia's Noren deployment, so everything is `NorenTickNormalizer`.
"""

from stock_brokers.instruments.ticks.noren import NorenTickNormalizer

class ShoonyaTickNormalizer(NorenTickNormalizer):
    """
    Normalizes Shoonya ticks.
    """

    BROKER_NAME = "shoonya"
