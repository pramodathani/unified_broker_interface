# Notes on `unified_broker_interface/utilities/order_engine/utilities/sequence_part.py`

## Starting the next child

`settle` walks the children in order and starts the first one that has neither started nor finished, with the quotes as they are now, then stops at the first that is not done. A child cancelled before it started is done, so a cancelled sequence starts nothing more.
