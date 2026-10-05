# Notes on `unified_broker_interface/utilities/order_engine/utilities/stages_pricing.py`

## How it differs from the design

The design's `stages` setter is a list of `{until, pricing}` pairs, where `until` is any condition. That general form is not built. `stages` here is today's stepped stop's milestone table, which is the only type that needs stages, with its rules unchanged: gains increasing, exactly one of `stop_at_gain` and `trail_points`, a trailing rule last, a stop never placed at or past the gain that moves it, at most 20 rules. The general form can replace it later without changing what `stepped_stop` means.

## What is kept in memory

`rules_applied`, and once trailing `trail_points` and `best`, are in the pricing's memory and recorded with the event of each move, so a restart keeps them (`a_plan_stepped_stop_keeps_its_milestones_across_a_restart`). A rule reached but skipped because it would loosen the stop changes the memory without a move, so it is not recorded; after a restart it is reached again and skipped again, which sends nothing different.

## Stale quotes (2026-10-05)

The group 6 walkthrough found every moving pricing acting on a quote marked `stale`: a peg followed a stale bid, a chaser crossed to a stale offer of 1005, an underlying peg moved on a stale index. The quote combiner marks a quote stale when its broker has gone silent and no healthy backup exists, so its price may be minutes old. This pricing now treats a stale quote as no quote, as `LimitMarketableCondition` always did: it neither places from it nor moves on it, and the next fresh quote moves the order as usual.
