# Notes on `unified_broker_interface/utilities/order_engine/utilities/moments.py`

## Why times are read in India rather than in the machine's timezone

Every time an order type is given is a wall-clock time on an Indian exchange's day, because that is how somebody says it: square off at ten past three. A server keeping UTC that read `15:10` as its own local time would square off five and a half hours late, which is to say after the market had closed and the broker had already done it.

So `Asia/Kolkata` is used explicitly and the machine's timezone never enters into it. The same reasoning is already in `bin/unified/orders/websocket_order_details`, which reckons its 06:00 reset in India.

## Why a time that has already passed is refused

`time_today` raises rather than rolling forward to tomorrow.

Rolling forward is the friendlier-looking choice and the wrong one. An order told to start at 09:30 when it is 10:00 is almost always a typo or a stale script, and the alternative reading — hold this order for eighteen hours and place it tomorrow morning, possibly into a gap, without anybody watching — is a large thing to do on an inference. Refusing costs a caller one corrected request; guessing costs them a position they did not know they had.

## Why durations and times of day are both allowed

`time_stop` takes either `until_time` or `minutes`, because the two things it is for are said differently. A square-off is a time of day: be out by ten past three. A momentum stop is a duration: if this has gone nowhere in twenty minutes, the idea has failed. Forcing either into the other's shape would mean the caller doing arithmetic that this can do instead.
