# `one_cancels_all.py`

## Why the legs are cancelled rather than reduced

The one-cancels-other type reduces its sibling by whatever filled, because both its legs are exits on one position and half an exit is a meaningful thing.

This is different. The candidates are separate trades on separate instruments, and half a candidate trade is not something anybody wanted: somebody who asked for whichever of three setups fires first, and got four units of one of them, has a position they did not size. So the first sign of a fill cancels the others outright.

## Why the double fill is worse here and is still not solved

More legs mean a higher chance that several fill before any cancel lands, and the Atlas says so directly. Nothing here makes it impossible, because only an exchange could and none offers the order type.

What is done is what can be done: the cancels go out on the first partial fill rather than on a complete one, so the window is as short as reading an update allows, and every fill and every cancel is in the event log so an account that ends up in two positions says so rather than being discovered at the close.
