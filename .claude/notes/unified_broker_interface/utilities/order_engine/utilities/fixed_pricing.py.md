# Notes on `unified_broker_interface/utilities/order_engine/utilities/fixed_pricing.py`

## Why the default leaves the body alone

`FixedPricing(None, None)` is the pricing every order gets when nothing else is named. It changes nothing, so the body's `price_reference` still reaches `concrete_order` and is resolved as for any order. `OrderPart.order` drops `price_reference` only when a pricing rule changed the price, because a reference and an explicit price cannot both apply.
