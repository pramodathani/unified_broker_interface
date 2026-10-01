# paper_venue.py

## Why a paper order is the whole plan (2026-10-01)

A paper fill trades nothing, so a Then join's child sized by it would be sent for real against a position that does not exist, and a sibling in a Together or Either join would mix real and imagined fills in one parent. Today's type is a single order, so the reader allows paper only at `root`.

## Why it waits on `limit_marketable` alone

The fills come from the virtual book's estimate, which exists only for an order held at its limit. Another trigger, or `limit_marketable` inside an `all` group, would leave the order with no estimate or one that does not describe it.

## Where the fills are counted

The paper fill count lives in the part record as `paper_filled`, recorded with a message so a restart replays it, and `PlanOrder._finish_if_done` adds it to what the legs traded, so a plan filled wholly on paper ends `completed` as today's type does.
