"""
Orders and trades from brokers on the Noren platform, Flattrade and Shoonya, from `OrderBook` and `TradeBook`.

**The requests.** Both are POSTs with a `jData` body the API client wraps and signs; `OrderBook` needs only the
user id the client adds, `TradeBook` the account as `actid` too, and a subclass says which settings field
holds it.

**Orders.** An order-book row carries the same fields a Noren order message does - measured against a rejected
Flattrade order on 2026-09-13: `norenordno`, `exchordid`, `status` and `rejreason`, `tsym` and `token` on
`exch`, `trantype`, `prd`, `prctyp`, `ret`, `qty`, `fillshares`, `cancelqty`, `dscqty`, `prc`, `trgprc`,
`avgprc`, `remarks`, `norentm` and `exch_tm`. The pending quantity is what is neither filled nor cancelled. An
`exch_tm` of `01-01-1980 00:00:00` is Noren's placeholder for an order the exchange never timestamped, and
reads as none.

**Trades.** Following Noren's published schema, a trade-book row carries `flid`, the fill id, with
`norenordno`, `exchordid`, the same instrument fields, `trantype`, `prd`, `flqty` and `flprc`, the quantity
and price filled, and `fltm` and `exch_tm`.

Noren answers HTTP 200 whether or not it served the request. An empty book is a `Not_Ok` saying "no data",
measured on both brokers, which is an empty answer; a dead session is Noren's refusal, as for holdings;
anything else is `OrdersUnavailable`.

**Writing.** An order is placed with `PlaceOrder` carrying `actid`, `exch` (`NSE`, `BSE`, `NFO`, `BFO`), `tsym`,
`qty`, `prc`, `trgprc`, `dscqty`, `prd` (`C`, `I`, `M`), `trantype` (`B`, `S`), `prctyp` in the long forms Noren's
own SDK uses (`MKT`, `LMT`, `SL-LMT`, `SL-MKT`), `ret`, `ordersource` `API`, `amo` and `remarks` for the tag;
Noren answers with `norenordno`. `ModifyOrder` restates the order - its exchange, symbol, product and side from
its row, its type, quantity, prices, disclosed quantity and validity with the changes laid over them - and
`CancelOrder` takes `norenordno`. Both answer with the order number in `result`. A refusal arrives as a `Not_Ok`
in an HTTP 200, and a refused session is raised as Noren's session refusal so the service logs in again.
"""

from unified_broker_interface.utilities.broker_holdings.utilities.noren import NorenHoldingsSource, NorenRefusal
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)

# What Noren says when the session key is no good, lowercased.
_AUTHENTICATION_MARKERS = ("session expired", "invalid session key", "invalid session")

# What Noren says when there is nothing to list, lowercased.
_NO_DATA_MARKER = "no data"

EXCHANGE_CODES = {("nse", "cash"): "NSE", ("bse", "cash"): "BSE", ("nse", "derivative"): "NFO",
                  ("bse", "derivative"): "BFO"}
ORDER_TYPE_CODES = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
PRODUCT_CODES = {"CNC": "C", "MIS": "I", "NRML": "M"}
SIDE_CODES = {"BUY": "B", "SELL": "S"}

# Noren's timestamp for an order the exchange never timestamped.
_NO_EXCHANGE_TIME = "01-01-1980 00:00:00"

def _exchange_time(value):
    """
    Noren's exchange timestamp, or None for its placeholder.
    """
    return None if not value or value == _NO_EXCHANGE_TIME else value

class NorenOrdersSource(BrokerOrdersSource):
    """
    Reads orders and trades from a Noren deployment. A subclass sets BROKER_NAME, BASE_URL and ACCOUNT_FIELD.

    Attributes:
        BASE_URL (str): The deployment's API root, before `/OrderBook` and `/TradeBook`.
        ACCOUNT_FIELD (str): The `settings` field holding the account id sent as `actid`.
    """

    BASE_URL = None
    ACCOUNT_FIELD = None
    WRITES_ENABLED = True

    def _book(self, client, path, body, name):
        response = client.post(url=f"{self.BASE_URL}/{path}", data=body, timeout=self.TIMEOUT_SECONDS)
        data = (response or {}).get("data")
        if isinstance(data, dict) and str(data.get("stat", "")).lower() != "ok":
            message = str(data.get("emsg") or data)
            if _NO_DATA_MARKER in message.lower():
                return []
            if any(marker in message.lower() for marker in _AUTHENTICATION_MARKERS):
                raise NorenRefusal(f"{self.BROKER_NAME} refused the session: {message[:200]}")
            raise OrdersUnavailable(f"{self.BROKER_NAME} refused the {name} request: {message[:200]}")
        if not isinstance(data, list):
            raise OrdersUnavailable(f"{self.BROKER_NAME} answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        # A fresh dict each time: the API client writes the user id into the one it is given.
        return self._book(client, "OrderBook", {}, "order book")

    def fetch_trades(self, client):
        return self._book(client, "TradeBook", {"actid": client._settings[self.ACCOUNT_FIELD]}, "trade book")

    def normalize_order(self, row):
        exchange, symbol = row.get("exch"), row.get("tsym")
        quantity = number(row.get("qty"), int)
        filled = number(row.get("fillshares"), int)
        cancelled = number(row.get("cancelqty"), int)
        pending = None
        if quantity is not None:
            pending = max(quantity - (filled or 0) - (cancelled or 0), 0)
        return order(
            self.BROKER_NAME, exchange,
            order_id=text(row.get("norenordno")),
            exchange_order_id=text(row.get("exchordid")),
            parent_order_id=text(row.get("snonum")),
            status=normalize(row.get("status"), STATUSES),
            status_message=row.get("rejreason") or None,
            id=f"{exchange}:{symbol}" if exchange and symbol else symbol,
            instrument_token=text(row.get("token")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("trantype"), TRANSACTION_TYPES),
            product=normalize(row.get("prd"), PRODUCTS),
            order_type=normalize(row.get("prctyp"), ORDER_TYPES),
            validity=normalize(row.get("ret"), VALIDITIES),
            quantity=quantity,
            filled_quantity=filled,
            pending_quantity=pending,
            cancelled_quantity=cancelled,
            disclosed_quantity=number(row.get("dscqty"), int),
            price=number(row.get("prc")),
            trigger_price=number(row.get("trgprc")),
            average_price=number(row.get("avgprc")),
            order_timestamp=row.get("norentm"),
            exchange_timestamp=_exchange_time(row.get("exch_tm")),
            tag=row.get("remarks"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exch"),
            trade_id=text(row.get("flid")),
            order_id=text(row.get("norenordno")),
            exchange_order_id=text(row.get("exchordid")),
            exchange_trade_id=text(row.get("flid")),
            instrument_token=text(row.get("token")),
            tradingsymbol=row.get("tsym"),
            transaction_type=normalize(row.get("trantype"), TRANSACTION_TYPES),
            product=normalize(row.get("prd"), PRODUCTS),
            quantity=number(row.get("flqty"), int),
            price=number(row.get("flprc")),
            trade_timestamp=row.get("fltm"),
            exchange_timestamp=_exchange_time(row.get("exch_tm")),
        )

    is_authentication_error = NorenHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        if not handle.get("order_symbol"):
            raise UnsupportedOrder(f"the {self.BROKER_NAME} mapping carries no trading symbol for {identity['instrument_id']}")
        form = {
            "exch": order_venue(self.BROKER_NAME, identity, EXCHANGE_CODES),
            "tsym": handle["order_symbol"],
            "qty": str(order_request["quantity"]),
            "prc": str(order_request["price"] or 0),
            "trgprc": str(order_request["trigger_price"] or 0),
            "dscqty": str(order_request["disclosed_quantity"] or 0),
            "prd": PRODUCT_CODES[order_request["product"]],
            "trantype": SIDE_CODES[order_request["transaction_type"]],
            "prctyp": ORDER_TYPE_CODES[order_request["order_type"]],
            "ret": order_request["validity"],
            "ordersource": "API",
            "amo": "YES" if order_request["after_market"] else "NO",
        }
        if order_request["tag"]:
            form["remarks"] = order_request["tag"]
        return {"method": "POST", "url": f"{self.BASE_URL}/PlaceOrder", "form": form}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        return {"method": "POST", "url": f"{self.BASE_URL}/ModifyOrder", "form": {
            "norenordno": str(row["norenordno"]),
            "exch": row.get("exch"),
            "tsym": row.get("tsym"),
            "prd": row.get("prd"),
            "trantype": row.get("trantype"),
            "prctyp": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "qty": str(values["quantity"]),
            "prc": str(values["price"] or 0),
            "trgprc": str(values["trigger_price"] or 0),
            "dscqty": str(values["disclosed_quantity"] or 0),
            "ret": values["validity"],
        }}

    def build_cancel(self, row):
        return {"method": "POST", "url": f"{self.BASE_URL}/CancelOrder", "form": {"norenordno": str(row["norenordno"])}}

    def account_fields(self, client, request):
        # A fresh dict each time: the API client writes the user id into the one it is given.
        form = dict(request.get("form") or {})
        if request["url"].endswith("/PlaceOrder"):
            form["actid"] = client._settings[self.ACCOUNT_FIELD]
        return {**request, "form": form}

    def send(self, client, request):
        response = super().send(client, request)
        data = (response or {}).get("data")
        if isinstance(data, dict) and str(data.get("stat", "")).lower() != "ok":
            message = str(data.get("emsg") or "")
            if any(marker in message.lower() for marker in _AUTHENTICATION_MARKERS):
                raise NorenRefusal(f"{self.BROKER_NAME} refused the session: {message[:200]}")
        return response

    def written_order_id(self, response):
        data = (response or {}).get("data")
        if not isinstance(data, dict):
            return None
        return text(data.get("norenordno") or data.get("result"))

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and str(data.get("stat", "")).lower() != "ok":
            return str(data.get("emsg") or "the broker refused the request")
        return None

    def is_rejection(self, exception):
        return str(getattr(exception, "code", "")) == "Not_Ok"
