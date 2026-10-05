# order_leg.py

## cancel_accepted (2026-10-05)

A caller's cancel of one broker order by its order id was recorded as a `leg_cancelled` event that no part of the parent read, so the leg stayed `acknowledged` and every moving pricing kept modifying it until the broker's update arrived; a discretionary order could even take a second time, buying 20 on a 10 order. `cancel_accepted` marks the leg when a broker accepts its cancel. It is written into the document only when true, so ordinary legs and the parents route's answers are unchanged.
