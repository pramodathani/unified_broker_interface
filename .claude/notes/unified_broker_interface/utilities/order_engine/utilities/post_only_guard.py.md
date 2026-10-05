# Notes on `unified_broker_interface/utilities/order_engine/utilities/post_only_guard.py`

## Why it copies the post-only type's rules

`would_cross`, `refuse` and `rest` are those of `post_only.py`. Today's type answers 409 before it records anything; a plan has already recorded the parent when the guard runs, so the plan answers 409 with the same message and the parent ends as `rejected`, through the part's `refused` reason.

## Why moves are checked too

Today's post-only type never moves its order. In a plan it can sit beside a peg, whose negative offset could take it through the touch, so a move is checked the same way: skipped with `refuse`, held at the own touch with `rest`.

## The waiting case

When the book cannot be read, `checked_body` answers no body and no refusal, so the order waits for a tick that carries a book, where today's type answers 503.

## Stale books (2026-10-05)

The guard used to judge a book marked stale like any other, so an order could be refused with 409, or moved to a touch, on prices minutes old (found in the group 6 walkthrough). A stale book now counts as unreadable: `checked_body` returns `(None, None)` so the order waits for a fresh book, as it already did with no book at all, and `checked_move` skips the move.
