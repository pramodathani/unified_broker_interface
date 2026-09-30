"""Reads prices from a depth topic and from a currency scrip topic, each with its own scale.

A depth topic keeps its multiplier and precision in fields 32 and 33 instead of the scrip topic's 23 and 24. `KotakFeedTopic.price` picks the right pair from the topic's kind, falls back to a multiplier of 1 and a precision of 2 when the feed has not sent them, and rounds to the precision so the division leaves no floating point noise.

This program builds a depth topic with a best bid of 2950.00 and a currency scrip topic with a precision of 4, and a scrip topic that never sent its scale. It needs no stand-ins.

Notice that the currency price keeps four decimal places, and that the topic without a scale reads its integer as paise.

Run it from the project root:

    python examples/stock_brokers/websockets/kotak/KotakFeedTopic/example_2_depth_and_currency_scale.py
"""


from stock_brokers.websockets.kotak import (
    KotakFeedTopic,
)


class DepthAndCurrencyScaleExample:
    """Reads prices from topics with different scales.

    Attributes:
        depth (KotakFeedTopic): A depth topic with a precision of 2.
        currency (KotakFeedTopic): A currency scrip topic with a precision of 4.
        unscaled (KotakFeedTopic): A scrip topic that has not sent its scale.
    """

    def __init__(self):
        """Builds and fills the three topics.

        Returns:
            None: This method returns nothing.
        """
        self.depth = KotakFeedTopic('dp', 'nse_cm|2885', {})
        depth_values = []
        for _ in range(34):
            depth_values.append(0)
        depth_values[2] = 295000
        depth_values[12] = 100
        depth_values[32] = 1
        depth_values[33] = 2
        self.depth.apply(depth_values)
        self.currency = KotakFeedTopic('sf', 'cde_fo|1234', {})
        currency_values = []
        for _ in range(25):
            currency_values.append(0)
        currency_values[5] = 835125
        currency_values[23] = 1
        currency_values[24] = 4
        self.currency.apply(currency_values)
        self.unscaled = KotakFeedTopic('sf', 'nse_cm|1594', {})
        unscaled_values = [
            0,
            0,
            0,
            0,
            0,
            150025,
        ]
        self.unscaled.apply(unscaled_values)

    def run(self):
        """Prints a price from each topic.

        Returns:
            None: This method returns nothing.
        """
        print(f'Depth best bid: {self.depth.price(2)} for quantity {self.depth.number(12)}')
        print(f'Currency last price: {self.currency.price(5)}')
        print(f'Last price without a scale: {self.unscaled.price(5)}')


if __name__ == '__main__':
    DepthAndCurrencyScaleExample().run()
