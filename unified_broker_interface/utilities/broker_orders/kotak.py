"""
Kotak Neo orders and trades, from `GET {base_url}/quick/user/orders` and `GET {base_url}/quick/user/trades`.

`base_url` is the host Kotak assigned the session at login. The requests are made here rather than through the
API client, because the client drops `timeout`, with the session's `Auth` and `Sid`. An empty book is
`{"stCode": 5203, "errMsg": "No Data", "stat": "Not_Ok"}`, measured on 2026-09-13 for both.

A row of `data` in the order book carries the same fields a Kotak order message does: `nOrdNo`, `exOrdId`,
`snoOrdNo`, `ordSt` and `rejRsn`, `trdSym` and `tok` in `exSeg` (`nse_cm`, `nse_fo`...), `trnsTp`, `prod`,
`prcTp`, `vldt`, `qty`, `fldQty`, `unFldSz`, `cnclQty`, `dscQty`, `prc`, `trgPrc`, `avgPrc`, `ordDtTm`,
`exCfmTm` and `usrRmk`. Following Kotak Neo's published schema, a trade-book row carries `flId`, the fill id,
with `nOrdNo`, `exOrdId`, the same instrument fields, `trnsTp`, `prod`, `fldQty` and `avgPrc`, the quantity and
price filled, `flDt` and `flTm`, and `exTm`.

**Writing - built, not enabled.** Kotak's API app is read-only: writes are refused as unauthorised. So the builds
exist and are checked offline, but Kotak is not offered to the router and a modify or cancel answers `501`, until
a sign-off test shows writes are allowed. An order would be placed with
`POST {base_url}/quick/order/rule/ms/place` and a `jData` form field of `es` (`nse_cm`, `bse_cm`, `nse_fo`, `bse_fo`),
`ts`, `qt`, `pr`, `tp`, `dq`, `pc`, `tt` (`B`, `S`), `pt` (`MKT`, `L`, `SL`, `SL-M`), `rt`, `mp` `0`, `pf` `N`,
`am` and `rm` for the tag, answered with `nOrdNo`; modified with `/quick/order/vr/modify` restating the order with
`no`, and cancelled with `/quick/order/cancel` and `on`.
"""

import json

import requests

from stock_brokers.api.kotak import KotakAPIException
from unified_broker_interface.utilities.broker_holdings.kotak import KotakHoldingsSource
from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   UnsupportedOrder, normalize, number, order,
                                                                   order_venue, text, trade)

ORDERS_PATH = "/quick/user/orders"
TRADES_PATH = "/quick/user/trades"

PLACE_PATH = "/quick/order/rule/ms/place"
MODIFY_PATH = "/quick/order/vr/modify"
CANCEL_PATH = "/quick/order/cancel"

SEGMENT_CODES = {("nse", "cash"): "nse_cm", ("bse", "cash"): "bse_cm", ("nse", "derivative"): "nse_fo",
                 ("bse", "derivative"): "bse_fo"}
ORDER_TYPE_CODES = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
SIDE_CODES = {"BUY": "B", "SELL": "S"}

# Kotak's status code for an answer with nothing in it.
NO_DATA_STATUS_CODE = 5203

def _first(row, *names):
    """
    The first of several fields a row carries a value for, or None.
    """
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None

class KotakOrdersSource(BrokerOrdersSource):
    """
    Reads Kotak orders and trades.
    """

    BROKER_NAME = "kotak"
    WRITES_BLOCKED_REASON = "has a read-only API app: order writes are refused as unauthorised"

    def _book(self, client, path, name):
        login = client._current_login() or {}
        headers = {"neo-fin-key": "neotradeapi", "Auth": str(login.get("access_token")), "Sid": str(login.get("sid"))}
        response = requests.get(client.url(path), headers=headers, timeout=self.TIMEOUT_SECONDS)
        if response.status_code >= 300:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        try:
            payload = response.json()
        except ValueError:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        if isinstance(payload, dict) and payload.get("stCode") == NO_DATA_STATUS_CODE:
            return []
        data = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(data, list):
            raise OrdersUnavailable(f"Kotak answered the {name} request without a {name}: {str(payload)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._book(client, ORDERS_PATH, "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_PATH, "trade book")

    def normalize_order(self, row):
        symbol, segment = _first(row, "trdSym", "sym"), _first(row, "exSeg", "exch")
        quantity = number(row.get("qty"), int)
        filled = number(row.get("fldQty"), int)
        pending = number(row.get("unFldSz"), int)
        if pending is None and quantity is not None and filled is not None:
            pending = quantity - filled
        return order(
            self.BROKER_NAME, segment,
            order_id=text(row.get("nOrdNo")),
            exchange_order_id=text(row.get("exOrdId")),
            parent_order_id=text(row.get("snoOrdNo")),
            status=normalize(_first(row, "ordSt", "stat"), STATUSES),
            status_message=_first(row, "rejRsn", "rejectionReason", "errMsg", "statMsg"),
            id=f"{segment}:{symbol}" if segment and symbol else symbol,
            instrument_token=text(row.get("tok")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("trnsTp"), TRANSACTION_TYPES),
            product=normalize(row.get("prod"), PRODUCTS),
            order_type=normalize(row.get("prcTp"), ORDER_TYPES),
            validity=normalize(_first(row, "vldt", "ret"), VALIDITIES),
            quantity=quantity,
            filled_quantity=filled,
            pending_quantity=pending,
            cancelled_quantity=number(row.get("cnclQty"), int),
            disclosed_quantity=number(row.get("dscQty"), int),
            price=number(row.get("prc")),
            trigger_price=number(row.get("trgPrc")),
            average_price=number(row.get("avgPrc")),
            order_timestamp=row.get("ordDtTm"),
            exchange_timestamp=_first(row, "exCfmTm", "boeSec"),
            tag=_first(row, "tag", "usrRmk", "remarks"),
        )

    def normalize_trade(self, row):
        fill_date, fill_time = row.get("flDt"), row.get("flTm")
        return trade(
            self.BROKER_NAME, _first(row, "exSeg", "exch"),
            trade_id=text(row.get("flId")),
            order_id=text(row.get("nOrdNo")),
            exchange_order_id=text(row.get("exOrdId")),
            exchange_trade_id=text(row.get("flId")),
            instrument_token=text(row.get("tok")),
            tradingsymbol=_first(row, "trdSym", "sym"),
            transaction_type=normalize(row.get("trnsTp"), TRANSACTION_TYPES),
            product=normalize(row.get("prod"), PRODUCTS),
            quantity=number(row.get("fldQty"), int),
            price=number(row.get("avgPrc")),
            trade_timestamp=f"{fill_date} {fill_time}" if fill_date and fill_time else fill_date or fill_time,
            exchange_timestamp=row.get("exTm"),
        )

    is_authentication_error = KotakHoldingsSource.is_authentication_error

    def build_place(self, order_request, identity, handle):
        if not handle.get("order_symbol"):
            raise UnsupportedOrder(f"the kotak mapping carries no trading symbol for {identity['instrument_id']}")
        fields = {
            "es": order_venue(self.BROKER_NAME, identity, SEGMENT_CODES),
            "ts": handle["order_symbol"],
            "qt": str(order_request["quantity"]),
            "pr": str(order_request["price"] or 0),
            "tp": str(order_request["trigger_price"] or 0),
            "dq": str(order_request["disclosed_quantity"] or 0),
            "pc": order_request["product"],
            "tt": SIDE_CODES[order_request["transaction_type"]],
            "pt": ORDER_TYPE_CODES[order_request["order_type"]],
            "rt": order_request["validity"],
            "mp": "0",
            "pf": "N",
            "am": "YES" if order_request["after_market"] else "NO",
        }
        if order_request["tag"]:
            fields["rm"] = order_request["tag"]
        return {"method": "POST", "url": PLACE_PATH, "form": {"jData": json.dumps(fields)}}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        fields = {
            "no": str(row["nOrdNo"]),
            "es": row.get("exSeg"),
            "ts": row.get("trdSym"),
            "pc": row.get("prod"),
            "tt": row.get("trnsTp"),
            "pt": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "qt": str(values["quantity"]),
            "pr": str(values["price"] or 0),
            "tp": str(values["trigger_price"] or 0),
            "dq": str(values["disclosed_quantity"] or 0),
            "rt": values["validity"],
            "mp": "0",
            "pf": "N",
            "am": "NO",
        }
        return {"method": "POST", "url": MODIFY_PATH, "form": {"jData": json.dumps(fields)}}

    def build_cancel(self, row):
        return {"method": "POST", "url": CANCEL_PATH, "form": {"jData": json.dumps({"on": str(row["nOrdNo"]), "am": "NO"})}}

    def send(self, client, request):
        login = client._current_login() or {}
        headers = {"neo-fin-key": "neotradeapi", "Auth": str(login.get("access_token")), "Sid": str(login.get("sid")),
                   "Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(client.url(request["url"]), data=request["form"], headers=headers,
                                 timeout=self.WRITE_TIMEOUT_SECONDS)
        if response.status_code >= 300:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])
        try:
            return {"data": response.json()}
        except ValueError:
            raise KotakAPIException(code=response.status_code, message=response.text[:300])

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("nOrdNo")) if isinstance(data, dict) else None

    def write_error(self, response):
        data = (response or {}).get("data")
        if isinstance(data, dict) and (data.get("stat") == "Not_Ok" or data.get("errMsg")):
            return str(data.get("errMsg") or "the broker refused the request")
        return None

    def is_rejection(self, exception):
        return str(getattr(exception, "code", "")) in ("400", "422")
