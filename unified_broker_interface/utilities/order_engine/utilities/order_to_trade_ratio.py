"""How many orders the engine sends for each one that actually trades, per broker."""


class OrderToTradeRatio:
    """Counts what the engine sends against what fills, which is what brokers police.

    Exchanges and brokers watch the order-to-trade ratio because an account that places and modifies far more than it trades loads the matching engine without adding liquidity. The types that will earn this — a peg re-pricing on every tick, a chaser walking towards the touch — are the ones Stage 8 adds, and when they arrive the ratio is what tells them to stop re-pricing rather than a fixed limit on modifications.

    For now it counts and reports. Nothing refuses an order on it yet, and saying so plainly is better than a limit that looks enforced and is not.

    A ratio is only meaningful once there is something to divide by, so a broker with no fills reports `None` rather than a very large number, which would otherwise read as a problem on the first order of the day.

    Attributes:
        sent (dict): Orders sent, by broker name.
        traded (dict): Orders that filled, wholly or partly, by broker name.
    """

    def __init__(self):
        """Builds empty counts.

        Returns:
            None: This method returns nothing.
        """
        self.sent = {}
        self.traded = {}

    def count_sent(self, broker_name):
        """Counts one order sent to a broker.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.sent[broker_name] = self.sent.get(broker_name, 0) + 1

    def count_traded(self, broker_name):
        """Counts one order that traded at a broker.

        Args:
            broker_name (str): The broker.

        Returns:
            None: This method returns nothing.
        """
        self.traded[broker_name] = self.traded.get(broker_name, 0) + 1

    def ratio(self, broker_name):
        """Orders sent for each one that traded at a broker.

        Args:
            broker_name (str): The broker.

        Returns:
            float | None: The ratio, or None when nothing has traded there yet.
        """
        traded = self.traded.get(broker_name, 0)
        if traded < 1:
            return None
        return round(self.sent.get(broker_name, 0) / traded, 3)

    def counts(self):
        """Every broker the engine has sent to, with what it sent, traded and the ratio.

        Returns:
            dict: One entry per broker name.
        """
        counted = {}
        for broker_name in sorted(self.sent):
            counted[broker_name] = {
                'sent': self.sent.get(broker_name, 0),
                'traded': self.traded.get(broker_name, 0),
                'ratio': self.ratio(broker_name),
            }
        return counted
