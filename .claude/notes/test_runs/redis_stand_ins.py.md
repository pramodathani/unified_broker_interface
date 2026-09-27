# Notes on `test_runs/redis_stand_ins.py`

## Why the stand-ins have a module of their own

The six Redis stand-ins used to live in three suites: the plain one in `order_routes`, the stream and list one in `order_engine_routes`, and the one the engine itself needs in `order_engine`. Each suite imported the one before it. Once direct placement was removed, the route suites had to run the real engine behind the place route, which needs the engine's stand-in, and `order_routes` importing `order_engine` would have been circular. Moving all six into one module that imports no suite breaks the cycle and puts every stand-in in one place to read.

The move changed no behaviour: every recording matched before and after.
