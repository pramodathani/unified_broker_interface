"""The taxes, fees and brokerage one trade pays, from the values it bought and sold."""

import decimal

RUPEE_PLACES = decimal.Decimal('0.01')


class TradeCharges:
    """Every charge on a set of fills in one segment and category, worked out the way a broker's bill works it out.

    The values are the rupees bought and sold, so the same object prices one round trip or a whole day of fills. Each charge is kept unrounded; a bill rounds some of them, such as STT and stamp duty to the rupee, so a bill can differ from these figures by under a rupee for each of those lines.

    Attributes:
        charge_rate (ChargeRate): The segment's statutory rates.
        buy_value (decimal.Decimal): The rupees bought.
        sell_value (decimal.Decimal): The rupees sold.
        brokerage (decimal.Decimal): The brokerage for every order behind the fills, in rupees, before GST.
    """

    def __init__(self, charge_rate, buy_value, sell_value, brokerage=decimal.Decimal(0)):
        """Builds the charges.

        Args:
            charge_rate (ChargeRate): The segment's statutory rates.
            buy_value (decimal.Decimal): The rupees bought.
            sell_value (decimal.Decimal): The rupees sold.
            brokerage (decimal.Decimal): The brokerage for every order, before GST; zero at a broker that charges none.

        Returns:
            None: This method returns nothing.
        """
        self.charge_rate = charge_rate
        self.buy_value = decimal.Decimal(buy_value)
        self.sell_value = decimal.Decimal(sell_value)
        self.brokerage = decimal.Decimal(brokerage)

    def turnover(self):
        """The value bought and sold together, which the exchange charge and the SEBI fee are taken on.

        Returns:
            decimal.Decimal: The turnover in rupees.
        """
        return self.buy_value + self.sell_value

    def stt(self):
        """Securities transaction tax.

        Returns:
            decimal.Decimal: STT on the buys and on the sells, in rupees.
        """
        bought = self.buy_value * self.charge_rate.stt_buy_rate
        sold = self.sell_value * self.charge_rate.stt_sell_rate
        return bought + sold

    def exchange_charge(self):
        """The exchange's transaction charge.

        Returns:
            decimal.Decimal: The charge on the turnover, in rupees.
        """
        return self.turnover() * self.charge_rate.exchange_rate

    def sebi_fee(self):
        """SEBI's turnover fee.

        Returns:
            decimal.Decimal: The fee on the turnover, in rupees.
        """
        return self.turnover() * self.charge_rate.sebi_rate

    def stamp_duty(self):
        """Stamp duty, which only the buyer pays.

        Returns:
            decimal.Decimal: The duty on the value bought, in rupees.
        """
        return self.buy_value * self.charge_rate.stamp_buy_rate

    def gst(self):
        """GST on the exchange charge, the SEBI fee and the brokerage.

        Returns:
            decimal.Decimal: The GST in rupees.
        """
        taxed = self.exchange_charge() + self.sebi_fee() + self.brokerage
        return taxed * self.charge_rate.gst_rate

    def total(self):
        """Every charge together, brokerage included.

        Returns:
            decimal.Decimal: The total in rupees.
        """
        statutory = self.stt() + self.exchange_charge() + self.sebi_fee() + self.stamp_duty()
        return statutory + self.gst() + self.brokerage

    def net_profit(self):
        """What the fills made after every charge.

        Returns:
            decimal.Decimal: The rupees sold less the rupees bought less the total charges.
        """
        return self.sell_value - self.buy_value - self.total()

    def parts(self):
        """Each charge rounded to the paisa, in the order a bill lists them.

        Returns:
            dict: `brokerage`, `stt`, `exchange_charge`, `sebi_fee`, `stamp_duty`, `gst` and `total`, each a decimal.Decimal in rupees.
        """
        return {
            'brokerage': self.brokerage.quantize(RUPEE_PLACES),
            'stt': self.stt().quantize(RUPEE_PLACES),
            'exchange_charge': self.exchange_charge().quantize(RUPEE_PLACES),
            'sebi_fee': self.sebi_fee().quantize(RUPEE_PLACES),
            'stamp_duty': self.stamp_duty().quantize(RUPEE_PLACES),
            'gst': self.gst().quantize(RUPEE_PLACES),
            'total': self.total().quantize(RUPEE_PLACES),
        }
