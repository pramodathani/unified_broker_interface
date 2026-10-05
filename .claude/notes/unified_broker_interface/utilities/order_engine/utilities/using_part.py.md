# using_part.py

## Copies made in advance (2026-10-02)

Like Repeat, Using is read into its copies when the plan is read, rather than creating parts as pieces are released, because every part must be rebuilt from the plan alone after a restart. That limits it to executions whose number of pieces is known in advance: the ladder (`steps`) and the timed executions with `over_minutes` (`slices`). VWAP is left out because its slice sizes depend on the clock when it starts; participation, iceberg and book depth because their number of pieces is not known.

## Each copy is an order with `each_piece` written on

A copy is the order without its execution, with `each_piece`'s presets added to the order's and its slot values added beside them, read as an ordinary order. That way a join preset such as bracket or cover expands around the piece exactly as it would around any order, and nothing in the join code knows about Using. A slot given in both is refused rather than one silently winning.

## Share, price and turn

Shares come from the execution's own arithmetic (`LadderExecution.quantities`, `TimedSlicesExecution.slice_quantities`), so they match what the execution would send. A ladder's rung price is written into the entry's part record as `piece_price` when the join starts, and `OrderPart.context` writes it over the body as a limit, which is why a pricing beside a ladder is refused. A timed copy's turn is an `elapsed` trigger added by the reader, counted from when the plan was placed rather than from when the execution would have begun, which is the same moment for an order with no trigger of its own.

## Never resized

`set_target` does nothing. The reader already refuses a Using join, as a together join, under a Then join, and a reducing Either join takes single orders only, so nothing would ask.

## Pieces in lots (2026-10-05)

Held pieces are shared out with the order's lot, so a held TWAP on a crude oil future gets whole-lot pieces.
