"""
Brokers' holdings endpoints and their rows, kept for what the order modules share with them.

`/api/portfolio/holdings` answers from `unified:portfolio:holdings`, which `bin/unified/holdings` keeps, so nothing
here serves it. What remains is what the orders modules in `broker_orders/` build on: `base.py`, with the holding's
shape and the exchange vocabulary, and the modules of the brokers whose orders module reuses its holdings client or
refusal handling - Dhan, Groww, INDmoney, Kotak, Wisdom Capital, Zerodha and, in `utilities/noren.py`, Flattrade and
Shoonya.
"""
