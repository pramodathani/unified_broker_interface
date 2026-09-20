# Notes on `unified_broker_interface/utilities/broker_orders/fyers.py`

## Why Fyers takes no after-market orders

Fyers' v3 API has an `offlineOrder` field, and the place request has always set it from `order.after_market`, so the class looked as though it supported after-market orders and inherited `TAKES_AFTER_MARKET = True` from `BrokerOrders`. It does not support them. On 2026-09-20 an after-market limit order for one KWIL share, routed to Fyers by the round-robin selector, came back rejected:

```json
{
  "code": -50,
  "message": "AMO order placement is not supported via API.",
  "s": "error"
}
```

The field exists in the payload but the API refuses the order whenever it is true. Setting `TAKES_AFTER_MARKET = False` makes `place_skip_reason` in `base.py` skip Fyers for after-market orders, the same way Groww and Wisdom Capital are already skipped, so the selector moves on to a broker that can take the order instead of spending a round trip on a rejection that is certain.

This mattered in practice rather than in principle. The default selector is `round_robin` over every broker that is not excluded, and with Groww and Wisdom Capital skipped that left eight brokers in the rotation for after-market orders, one of which rejected every one it was given. Roughly one after-market order in eight was failing for no reason other than which broker's turn it was, and the failure was invisible in a dry run, because a dry run stops before the broker answers.

`offlineOrder` stays in `build_place_request`. Fyers expects the field, and it is now always `False`, because an order with `after_market` set no longer reaches this class.

## How this was found

The order was placed deliberately, as a real one-share order through the whole path, while testing every endpoint of the REST API from the sibling `tradingmachine` project. Nothing about the rejection was visible from the code alone: the class carries the `offlineOrder` field, the base class defaults the flag to true, and the request the dry run builds looks correct. Only the broker's own answer showed that the order could never be accepted.
