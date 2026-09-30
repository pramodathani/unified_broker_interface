"""Each broker's own margin calculator, asked once a day to measure how much more than the exchange's margin the broker charges.

`base.py` holds `BrokerMarginCalculator`, the class every broker's calculator subclasses, and each other module holds one broker's. `utilities/` holds the reference orders they are all asked about, the calibration that compares their answers, and the registry. Nothing here runs while an order is placed: the lowest-cost selector estimates margin from the tables this calibration writes, and never waits on a broker.

Stoxkart has no margin calculator, so it has no module here.
"""
