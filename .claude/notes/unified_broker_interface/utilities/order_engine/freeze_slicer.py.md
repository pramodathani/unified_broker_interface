# Notes on `unified_broker_interface/utilities/order_engine/freeze_slicer.py`

## Why the freeze quantity is read from the broker the order is going to

The build plan listed this type as blocked on the freeze quantity, which is not in the order handle. It is in `unified:catalogue:<date>:additional_attributes`, published by five of the ten brokers, and reading it was the easy part. Reading it *correctly* was not.

For one MCX silver option the published values are these:

| Broker | Lot size | Freeze quantity |
| --- | --- | --- |
| dhan | 1 | 11 |
| groww | 30 | 600 |
| kotak | 30 | 600 |
| wisdom_capital | 1 | 20 |

Groww's 600 and Wisdom Capital's 20 are the same limit, twenty lots, written in each broker's own quantity terms — exactly as `CLAUDE.md` says values are stored, as the broker sent them and never scaled. Comparing Groww's 600 against a quantity expressed the way Wisdom Capital expresses quantities would be wrong by a factor of thirty, and would slice a perfectly legal order into thirty pieces or fail to slice one that needed it.

So the limit is read for the chosen broker and compared against `PreparedPlacement.broker_quantity`, which is the quantity that broker's request actually carries. Dhan's 11 against the others' 20 is a disagreement between brokers about the limit itself, which this handles by simply using whichever broker the order is going to.

## Why a broker that publishes no limit gets the order whole

Half the brokers publish nothing. The order is sent whole and the event log says no limit was known.

The alternatives are worse. Guessing from another broker means the unit problem above, with nothing to check the guess against. Refusing the order means half the brokers cannot take a large derivative order at all, through a route whose whole purpose is to place orders. An exchange rejection is a visible, recorded, recoverable failure, and it is the honest outcome of not knowing.

## Why the split is even rather than filling each slice

Two hundred and fifty units with a limit of a hundred becomes 84, 83, 83 rather than 100, 100, 50.

A run of maximum-sized orders followed by one small one is a recognisable shape in a public order book. And if the limit changes during the day, which it can, an even split leaves every slice the same distance from it rather than several sitting exactly on the old one.

## Why twenty slices is the ceiling

An order five hundred times the freeze limit is far more likely to be a quantity typed with too many zeros than a genuine intention to send five hundred orders. Five hundred orders would also exhaust the rate budget for a minute, during which nothing else could be placed, including anything trying to close a position.

Refusing is recoverable in a way that sending is not.
