# `cross_instrument.py`

## Why the pairing is not checked

Nothing here verifies that the watched instrument is the traded one's underlying, or related to it at all. There is no relationship the engine could confirm — the mapping tables know an option's underlying but nothing about a stock and its sector index — and there are plenty of useful pairs that are not underlyings: a calendar spread's near leg watching the far one, a commodity watching the dollar, a stock watching the index it is heavy in.

A check would therefore have to be a list of allowed relationships, which would be wrong on the day somebody wants a pair that is not on it, and would be doing so by refusing an order rather than by asking.

## Why the watched instrument is a parameter read by name

`watch_instrument_id` is read by `PriceTicker.instruments_of` as well as by this class. The ticker has to know which quotes to fetch before it builds a runner for anything, and building a runner for every open parent in order to ask each one what it watches would undo the saving that reading every quote in one call was for.

The cost is that one parameter name is known in two places rather than one. That is the smaller cost, and it is recorded in both docstrings.
