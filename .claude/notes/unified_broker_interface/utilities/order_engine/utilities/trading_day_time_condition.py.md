# trading_day_time_condition.py

## Why a condition of its own (2026-10-02)

`TimeCondition` reaches only the next trading day, and refuses a passed time, which suits a scheduled order. A daily Repeat needs the time on the first, second, third trading day and so on from placement, with a passed time today rolling to the next trading day rather than being refused. Counting trading days with `TradingDays` keeps weekends and the exchange's holidays out, from the same calendar files the tick pipeline reads.

## The moment is kept in memory

The moment is worked out when the plan is placed and kept as `at`, as `TimeCondition` keeps its own, so a carried plan replayed after the 06:00 reset fires on the day worked out at placement, not one recounted from the restart.
