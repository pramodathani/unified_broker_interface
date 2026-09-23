# Notes on `unified_broker_interface/utilities/order_engine/oco.py`

## The double fill, which this whole class is written around

Two exits rest at the exchange. In a fast market both can fill before any cancel arrives, and the account ends up with a position twice the size it started with, in the opposite direction, unattended. The Atlas names this as the recurring bug in every linked order type, and no exchange offers an order that prevents it.

So the class cannot make it impossible. What it can do is make the window as small as reading an update allows, and make the answer visible in the event log when it happens anyway.

## Why the sibling is reduced rather than cancelled

When one exit fills four of ten, the other is changed to six. It is not cancelled and replaced.

Cancelling leaves a window with nothing protecting the position, which is the situation the pair exists to avoid; it is a strange trade to make in the name of tidiness. Replacing also loses the order's place in the queue, and sends two requests where one change would do, which costs rate budget the engine may need for something more urgent.

## Why a partial fill is acted on immediately

The reaction happens on any fill, not on a leg completing. An exit oversized by the amount another has already filled is an exit that will, if it fills, close more than is held and open a position the other way.

## Why the engine cannot simply keep one leg resting

The Atlas offers a variant that avoids the problem entirely: keep only the stop at the exchange and watch the target in your own code, firing a marketable limit when it is reached. Only one leg ever rests, so a double fill is impossible.

That is not what this class does, and the reason is the one the Atlas itself gives for keeping native orders: a leg resting at the exchange goes on protecting the position while the engine is down, and a target watched in the engine's own code does not. Choosing the hidden-target variant would trade a rare, recorded double fill for a common, silent loss of protection during a restart. The engine already restarts for a deploy.

## Why the parent finishes on `live_legs` rather than on a position check

The Atlas's third rule is to check the position after every update. This class instead closes the parent when none of its own legs can still fill.

They are not the same thing, and the difference is deliberate. The parent is a record of what this order did, and it is finished when it has nothing left at a broker. Whether the account is flat is a question about the account, which may hold positions from a dozen other sources, and answering it here would make one order's lifetime depend on another's. The position check belongs in the reconciliation the engine does at startup and in `POST /api/orders/flatten`, both of which look at the account as a whole.
