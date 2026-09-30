# Notes on `unified_broker_interface/utilities/broker_selection/utilities/margin_estimate.py`

## Where the rules came from

Each rule was checked on 2026-09-30 against the margin calculators of Zerodha, Dhan, Fyers, Groww, INDmoney, Kotak, Flattrade, Shoonya and Wisdom Capital, for the same orders at the same prices. Six brokers agreed with each other to within half a percent, which is the exchange's own margin; the estimate lands within 1% of that for delivery, intraday, futures and bought options. `test_runs/funds_check.py` pins those comparisons.

A sold option is charged its underlying's value times the futures rate. On that day a sold at-the-money NIFTY call needed 161,608 at the brokers and a NIFTY future 167,109, so the rule is about 3% cautious for an at-the-money option and more cautious the further out of the money the option is. It never came out below the brokers.

## Hedge benefit

The hedged formula is the maximum loss at expiry (premiums left out), plus exposure on every sold option and future, plus premiums paid. Groww's calculator broke its condor answer into SPAN 12,761.25, exposure 59,059.65 and option premium 3,705, and those three match the formula's three terms (13,000, 59,075.25 and 3,711.50). Zerodha's answer was about 8,700 lower because it also credits the premium received on the sold legs, which the estimate deliberately does not.

Only legs on one underlying with one expiry are hedged. Across expiries the worst case depends on volatility, not on a payoff at expiry, so calendar spreads are added up.

## The highest point, not the end state

A broker checks each order when it arrives, so the estimate walks the legs in send order and takes the largest requirement at any prefix. Two sold options before their protection form a short strangle whose loss has no limit, so the estimate adds them up (about 333,000 for the condor), which is more cautious than the brokers: Zerodha's `initial` figure for the sold-first order was 187,651, because SPAN offsets a strangle's two sides against each other. The user was told this and accepted a cautious estimate.
