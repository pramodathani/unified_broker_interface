# Notes on `unified_broker_interface/utilities/margin_calculators/utilities/margin_calibration.py`

## Why the median of the brokers stands for the exchange

The exchange publishes its margins in SPAN and VaR files, but nothing in the project downloads them yet, and the brokers' calculators are the authoritative figures the user asked for. On 2026-09-30 six of the nine brokers with a calculator (Zerodha, Dhan, Fyers, Groww, INDmoney, Kotak) agreed to within half a percent for every reference order, and the three with surcharges (Flattrade, Shoonya, Wisdom Capital) were always above them. With nine answers the median is therefore always one of the six, so it is the exchange's figure to within that half percent. With an even number of answers, such as crude oil where Groww, INDmoney and Wisdom Capital give none, the median averages the two middle answers; that is still among the agreeing brokers.

The median moves slightly day to day (on 2026-09-30 the intraday median was Fyers' 204.55 rather than Zerodha's 203.48), so a surcharge-free broker can come out at 0.99something. Multipliers are floored at 1.000 so rounding noise never tells the selector a broker is cheaper than the exchange.

## Why hedge benefit is under 40%, not under 60%

The first version used 60%. The live dry run on 2026-09-30 at 11:35 IST showed Fyers' condor basket at 181,158.47 against 308,000.12 for its legs, 59%, which passed. That figure is a partial offset between the two sold legs (SPAN treats a short strangle as less risky than two naked shorts), not the defined-risk pricing of the whole condor that `MarginEstimate.hedged_margin` assumes. The brokers that do price the condor as a spread answered 22% to 25%. 40% sits well clear of both groups.

## Why unmeasured figures are written as NULL through COALESCE

A calculator that fails on one order (Wisdom Capital answered 0 for crude oil) must not erase a figure measured on an earlier day, or seeded by hand. `COALESCE(%s, column)` writes only what was measured. `margin_calibrated_at` is written whenever anything was, which also stops the DDL seed from filling cells for that broker again.

## Why this script calls brokers from bin/unified/

The architecture says `bin/unified/` reads only Redis and the database. The order engine in `bin/unified/orders/` is the existing exception, because placing an order has to reach a broker; this script follows it, and only calls endpoints that price an order and place nothing. It never logs in: a broker whose Redis login is missing is skipped.
