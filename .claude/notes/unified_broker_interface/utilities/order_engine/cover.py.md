# `cover.py`

## Why refusing a target is the whole type

`Cover` is `Bracket` plus two lines of validation, and somebody will reasonably ask why it is a type at all rather than a bracket with the target left out.

Because a bracket with the target left out is a bracket that happens to have no target, and a cover order is an order that *cannot* have no stop. Brokers gave higher leverage on cover orders precisely because the stop is structural: an order whose worst case is known is an order whose margin can be smaller. Letting the two shade into each other would mean somebody asking for a cover order and getting one with no stop, which is the one outcome the name rules out.

Refusing a target rather than ignoring it is the same argument from the other side. Somebody who supplied one meant something by it, and quietly dropping it would leave them believing they had a target they do not have.
