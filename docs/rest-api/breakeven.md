# Breakeven levels

This route tells a strategy where to put a breakeven stop so that it really breaks even. It answers three levels for one position in one instrument, worked out from the taxes and fees of the segment, the broker's brokerage, how far stops in that segment have recently slipped, how much the instrument's price flickers, and its live spread. [Trade charges and the real breakeven](../architecture/trade-charges.md) explains each level.

| Level | What it is | What it is for |
|---|---|---|
| `floor` | The exit price at which the position makes exactly nothing after every charge | The worst a breakeven exit should fill at |
| `tripwire` | The floor moved away from the market by the slip such stops show | The trigger to give the stop |
| `switch_on` | The tripwire moved further away by the instrument's flicker | The price the watched side must reach before the stop is moved to the tripwire |

For a position opened by buying, the three levels sit above the entry in that order. For one opened by selling, they sit below it.

## Breakeven

<div class="endpoint" markdown><span class="method get">GET</span> `/api/instruments/breakeven`<span class="auth">access-token</span></div>

#### Request parameters

The instrument is named as on every instrument route, by `instrument_id` or by its identity fields; see [naming an instrument](instruments.md#naming-an-instrument).

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `access-token` | header | string | Yes | The token from [`connect`](session.md#connect) |
| `instrument_id` | query | string | Yes, or the identity fields | The instrument |
| `entry_price` | query | number | Yes | The position's average opening price, above zero |
| `quantity` | query | integer | Yes | The position's size in units, at least `1` |
| `side` | query | string | No | `BUY` for a position opened by buying, the default, or `SELL` |
| `product` | query | string | No | `NRML`, the default, `MIS` or `CNC`. It decides the charges of a share: `CNC` is delivery and anything else intraday. A future or an option pays the same charges whatever the product. |
| `broker` | query | string | No | The broker the orders go to. When it is left out, the broker charging least brokerage for the trade is used, the first by name among equals, which is the broker the lowest-cost selector prefers when none is busy. |
| `percentile` | query | integer | No | Which percentile of the measured stop slips and of the flicker to allow for, from `1` to `99`. The default is `90`. |
| `horizon_seconds` | query | integer | No | How many seconds ahead the flicker is measured, from `1` to `300`. The default is `5`. |

#### Example

=== "curl"

    ```bash
    curl "http://127.0.0.1:8080/api/instruments/breakeven?instrument_id=b546e617-303e-53d7-b888-3fd0256bafad&entry_price=177&quantity=65" \
      -H "access-token: $ACCESS_TOKEN"
    ```

=== "Python"

    ```python
    import os

    import requests

    response = requests.get(
        'http://127.0.0.1:8080/api/instruments/breakeven',
        headers={
            'access-token': os.environ['ACCESS_TOKEN'],
        },
        params={
            'instrument_id': 'b546e617-303e-53d7-b888-3fd0256bafad',
            'entry_price': 177,
            'quantity': 65,
        },
        timeout=10,
    )
    levels = response.json()
    ```

#### Response

The example below is the NIFTY 27 October 2026 22850 call, worked out on the night of 19 October 2026, when the quote was the closing book.

```json
{
  "instrument_id": "b546e617-303e-53d7-b888-3fd0256bafad",
  "segment": "nse_equity_index_options",
  "category": "fno",
  "broker": "flattrade",
  "brokerage_per_order": "0",
  "opening_side": "BUY",
  "entry_price": "177",
  "quantity": 65,
  "tick_size": "0.05",
  "spread": "2.95",
  "percentile": 90,
  "floor": {
    "price": "177.45",
    "exact_price": "177.4205",
    "distance_from_entry": "0.45",
    "charges_checked_on": "2026-10-19"
  },
  "tripwire": {
    "price": "178.70",
    "distance_from_entry": "1.70",
    "source": "measured",
    "slip_basis_points": "69.93",
    "stops_measured": 225
  },
  "switch_on": {
    "price": "179.50",
    "distance_from_entry": "2.50",
    "source": "measured",
    "flicker": "0.8000",
    "ticks_measured": 2247,
    "horizon_seconds": 5
  }
}
```

#### Response attributes

Every price is text, so that no digit is lost to floating point.

| Attribute | Type | Description |
|---|---|---|
| `instrument_id`, `segment` | string | The instrument and its segment |
| `category` | string | `fno`, `delivery` or `intraday`, the kind of trade whose charges apply |
| `broker`, `brokerage_per_order` | string | The broker used and its brokerage for one order of the category, before GST |
| `opening_side`, `entry_price`, `quantity` | string, string, integer | The position as asked |
| `tick_size` | string or null | The tick the levels are rounded to, from the instrument's details; null leaves them unrounded |
| `spread` | string or null | The live gap between the best bid and the best ask, or null without a quote |
| `percentile` | integer | The percentile allowed for |
| `floor.price` | string | The breakeven, rounded to the tick on the side that never loses |
| `floor.exact_price` | string | The same before rounding |
| `floor.distance_from_entry` | string | How far the floor is from the entry, in the direction the position needs the price to go |
| `floor.charges_checked_on` | string or null | The day the segment's charge rates were last checked against a broker's bill, or null when they never have been |
| `tripwire` | object or null | The trigger, or null when there is neither a measured slip nor a spread |
| `tripwire.source` | string | `measured` when it used the percentile of `stops_measured` recent stops' slips, `slip_basis_points`, or `spread` when it used the spread plus two ticks |
| `switch_on` | object or null | The switch-on, or null when the tripwire is null or there is neither a measured flicker nor a spread |
| `switch_on.source` | string | `measured` when it used `flicker`, the percentile of the moves of `ticks_measured` recent ticks over `horizon_seconds`, or `spread` when it used the spread plus two ticks |

#### Status codes

| Status | When |
|---|---|
| <span class="status s2">200</span> | The levels were worked out. The tripwire and the switch-on may still be null. |
| <span class="status s4">400</span> | `entry_price is required`, `entry_price must be a number`, `entry_price must be above zero`, `quantity is required`, `side must be BUY or SELL`, a message about `percentile`, `horizon_seconds` or a number out of range, or a message about naming the instrument. |
| <span class="status s4">401</span> | `Access token is required`, `Invalid access token` or `Access token has expired`. |
| <span class="status s4">404</span> | The instrument is not known. |
| <span class="status s4">409</span> | `The taxes and fees of <segment> <category> trades are not known; add a row to unified.charge_rates.`, or `The brokerage of <broker> is not known; add a row to unified.broker_order_costs.` |
| <span class="status s5">503</span> | `no instruments have been mapped yet` or `the instrument cache is unreachable`, from the instrument catalogue. |

The charge rates, the broker costs and the measured stop slips are read on the first request of each day in India, in each worker, and kept for the day. The flicker is read from `unified.ticks` on every request, from the last 30 minutes of the instrument's latest session in the last five days.
