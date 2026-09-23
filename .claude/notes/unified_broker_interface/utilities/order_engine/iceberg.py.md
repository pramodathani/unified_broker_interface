# `iceberg.py`

## Why this loses what the exchange's own version keeps

NSE offers disclosed quantity natively in the cash segment, and it keeps the order's original time priority across every replenishment: the hidden part never loses its place in the queue.

This cannot. Each slice is a new order that joins the back of its price level's queue, so an iceberg built this way fills materially more slowly than the native one at the same price. Where disclosed quantity is available it is the better tool, and this exists for the segments and brokers where it is not.

## Why the randomisation uses a checksum

`randomise_percent` varies the visible size so that a bid replaced at exactly five hundred, five times running, does not announce itself. But it has to be reproducible: a recorded scenario must give the same slice sizes on every run, and a parent must get the same sizes after an engine restart as before it.

Python's `hash` of a string is salted differently in every process, so it would have given different sizes after every restart and no recording of it could ever have matched. `zlib.crc32` of the parent id and the slice number is stable everywhere, and is as unguessable from outside the account as a random draw, because nobody outside the account knows the parent id.
