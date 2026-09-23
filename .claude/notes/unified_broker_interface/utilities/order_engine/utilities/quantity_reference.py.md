# Notes on `unified_broker_interface/utilities/order_engine/utilities/quantity_reference.py`

## Why closing decides the side as well as the quantity

`reduce_position` and `liquidate_position` return a transaction type along with a quantity, overriding whatever the caller asked for.

Closing a long is selling and closing a short is buying. A caller who has to work that out themselves has to know the sign of a position they may not have read recently, and the failure when they get it wrong is not an error message: it is an order that doubles the position instead of closing it, in the direction that was already losing. That is precisely the arithmetic somebody gets wrong at the moment they most want it right.

## Why `reduce_position` treats the quantity as a ceiling

Asking to reduce by 500 when 75 are held closes 75, not 500 and not an error. The caller's number is what they are willing to close, not an instruction to sell short by the difference.

An order refused for being too large would be defensible, and was rejected because the situation it happens in is one where somebody is trying to get out. Closing what there is to close is the useful answer.

## Why quantities here are in units

These are units, as `POST /api/orders/place` takes them, not a broker's lots. The conversion into a broker's own terms happens afterwards and unchanged, so a reduce that does not come to a whole number of lots is refused by exactly the check that refuses a caller's own number.

That matters for the currency and commodity contracts, where a broker's lot is not the same as another broker's, and where `unified.contract_sizes` is the only trusted source. Doing the conversion here would have meant a second place that knows about lots, and one of the two would eventually be wrong.

## Why no position at all is a refusal rather than a success

Asking to liquidate when nothing is held answers HTTP 409 rather than doing nothing and reporting success.

Both are defensible. The refusal was chosen because the two situations a caller is in are opposite: either they believe they hold something and are wrong, which they need to know immediately, or they are closing defensively and a quiet success would tell them they are flat when the engine simply could not see the position. The second is the one that costs money.
