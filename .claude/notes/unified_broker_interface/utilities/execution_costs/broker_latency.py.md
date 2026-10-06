# Notes on `broker_latency.py`

## Why a plain mean, after a trimmed mean was tried

The first version used a 5% trimmed mean (drop the highest and lowest twentieth, average the rest) so that one price jump could not decide a broker's figure. Run on the real table on 2026-10-06, it gave exactly 0.00 for every broker and category. More than 90% of legs had a latency cost of zero, because the mid-price usually does not move in the 50 to 90 ms a broker takes to answer, so the handful of legs that did move were precisely the ones the trim removed. The plain mean then gave Flattrade -0.44 and Zerodha +1.35 basis points on F&O.

The latency cost is a rare-event quantity: its expected value is what an order pays on average, and the mean is the estimate of that. Protection against one lucky or unlucky jump comes from the 30-leg minimum and the 20-day window instead.

## `FEWEST_LEGS = 30`

A common rule-of-thumb sample size for a mean. With a cost that is zero on most legs, thirty legs is still noisy; stage 4a, when it reads these figures, should weigh that, and the calibration could later store the leg counts if the selector needs them.

## Answer time as a median

The answer time is a well-behaved quantity, mostly between 40 and 120 ms with occasional long stalls, so the median describes a broker's typical speed without being moved by the stalls. It is stored for a person to read and is not meant to be priced directly.
