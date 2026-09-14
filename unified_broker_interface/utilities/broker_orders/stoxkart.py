"""
Stoxkart orders and trades, from `GET https://openapi.stoxkart.com/reports/order-book` and
`GET https://openapi.stoxkart.com/reports/trade-book`.

The API client unwraps Stoxkart's `data`. The fields are an unconfirmed reading, since no populated book
has been seen: orders carry `order_id`, `exchange_order_id`, `status` and `status_message`, `trading_symbol`
and `token` on `exchange`, `transaction_type`, `product`, `order_type`, `validity`, `quantity`,
`filled_quantity`, `pending_quantity`, `price`, `trigger_price`, `average_price`, `order_timestamp` and
`exchange_timestamp`; trades carry `trade_id`, `order_id`, the same instrument fields, `transaction_type`,
`product`, `quantity`, `price` and `trade_time`.

Stoxkart's login is a known issue that is left alone, so a refused session is reported as Stoxkart failing
and never logged in from here.

**Writing - built, not enabled.** Stoxkart's session is not kept alive, and every write needs an algo identifier
the account does not have. So the builds exist and are checked offline, but Stoxkart is not offered to the router. An order
would be placed with `POST /orders/normal` - `/orders/amo` after the market - and a JSON body of `exchange`,
`token`, `action`, `order_type` (`MARKET`, `LIMIT`, `STOPLOSS_LIMIT`, `STOPLOSS_MARKET`), `product_type`
(`DELIVERY`, `INTRADAY`, `CARRYFORWARD`), `quantity`, `disclose_quantity`, `price`, `trigger_price`,
`stop_loss_price`, `trailing_stop_loss`, `validity`, `algo_id` and `tag`; modified with
`PUT /orders/{variety}/{order_id}` restating it, and cancelled with `DELETE`.
"""

from unified_broker_interface.utilities.broker_orders.base import (ORDER_TYPES, PRODUCTS, STATUSES, TRANSACTION_TYPES,
                                                                   VALIDITIES, BrokerOrdersSource, OrdersUnavailable,
                                                                   normalize, number, order, order_venue, text, trade)

ORDERS_URL = "https://openapi.stoxkart.com/reports/order-book"
TRADES_URL = "https://openapi.stoxkart.com/reports/trade-book"
WRITE_URL = "https://openapi.stoxkart.com/orders"

EXCHANGE_CODES = {("nse", "cash"): "NSE", ("bse", "cash"): "BSE", ("nse", "derivative"): "NFO",
                  ("bse", "derivative"): "BFO"}
ORDER_TYPE_CODES = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOPLOSS_LIMIT", "SL-M": "STOPLOSS_MARKET"}
PRODUCT_CODES = {"CNC": "DELIVERY", "MIS": "INTRADAY", "NRML": "CARRYFORWARD"}

class StoxkartOrdersSource(BrokerOrdersSource):
    """
    Reads Stoxkart orders and trades.
    """

    BROKER_NAME = "stoxkart"
    WRITES_BLOCKED_REASON = "has no live session and no algo identifier, which every write needs"

    def _book(self, client, url, name):
        data = (client.get(url=url, timeout=self.TIMEOUT_SECONDS) or {}).get("data")
        if data in (None, {}):
            return []
        if not isinstance(data, list):
            raise OrdersUnavailable(f"Stoxkart answered the {name} request without a {name}: {str(data)[:200]}")
        return data

    def fetch_orders(self, client):
        return self._book(client, ORDERS_URL, "order book")

    def fetch_trades(self, client):
        return self._book(client, TRADES_URL, "trade book")

    def normalize_order(self, row):
        exchange = row.get("exchange")
        symbol = row.get("trading_symbol") or row.get("tradingsymbol")
        return order(
            self.BROKER_NAME, exchange,
            order_id=text(row.get("order_id")),
            exchange_order_id=text(row.get("exchange_order_id")),
            status=normalize(row.get("status"), STATUSES),
            status_message=row.get("status_message") or None,
            id=f"{exchange}:{symbol}" if exchange and symbol else symbol,
            instrument_token=text(row.get("token")),
            tradingsymbol=symbol,
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            order_type=normalize(row.get("order_type"), ORDER_TYPES),
            validity=normalize(row.get("validity"), VALIDITIES),
            quantity=number(row.get("quantity"), int),
            filled_quantity=number(row.get("filled_quantity"), int),
            pending_quantity=number(row.get("pending_quantity"), int),
            price=number(row.get("price")),
            trigger_price=number(row.get("trigger_price")),
            average_price=number(row.get("average_price")),
            order_timestamp=row.get("order_timestamp"),
            exchange_timestamp=row.get("exchange_timestamp"),
        )

    def normalize_trade(self, row):
        return trade(
            self.BROKER_NAME, row.get("exchange"),
            trade_id=text(row.get("trade_id")),
            order_id=text(row.get("order_id")),
            instrument_token=text(row.get("token")),
            tradingsymbol=row.get("trading_symbol") or row.get("tradingsymbol"),
            transaction_type=normalize(row.get("transaction_type"), TRANSACTION_TYPES),
            product=normalize(row.get("product"), PRODUCTS),
            quantity=number(row.get("quantity"), int),
            price=number(row.get("price")),
            trade_timestamp=row.get("trade_time"),
        )

    def is_authentication_error(self, exception):
        # Stoxkart is never logged in from here; see the module docstring.
        return False

    def _order_fields(self, exchange, token, side, values, product):
        trigger_price = str(values["trigger_price"] or 0)
        return {
            "exchange": exchange,
            "token": str(token),
            "action": side,
            "order_type": ORDER_TYPE_CODES.get(values["order_type"], values["order_type"]),
            "product_type": PRODUCT_CODES.get(product, product),
            "quantity": str(values["quantity"]),
            "disclose_quantity": str(values["disclosed_quantity"] or 0),
            "price": str(values["price"] or 0),
            "trigger_price": trigger_price,
            "stop_loss_price": trigger_price,
            "trailing_stop_loss": "0",
            "validity": values["validity"],
            "algo_id": "0",
        }

    def build_place(self, order_request, identity, handle):
        body = self._order_fields(order_venue(self.BROKER_NAME, identity, EXCHANGE_CODES), handle["broker_token"],
                                  order_request["transaction_type"], order_request, order_request["product"])
        if order_request["tag"]:
            body["tag"] = order_request["tag"]
        variety = "amo" if order_request["after_market"] else "normal"
        return {"method": "POST", "url": f"{WRITE_URL}/{variety}", "json": body}

    def build_modify(self, row, changes):
        values = self.modified_values(row, changes)
        body = self._order_fields(row.get("exchange"), row.get("token"), row.get("transaction_type"), values,
                                  normalize(row.get("product"), PRODUCTS))
        return {"method": "PUT", "url": f"{WRITE_URL}/{row.get('variety') or 'normal'}/{row['order_id']}", "json": body}

    def build_cancel(self, row):
        return {"method": "DELETE", "url": f"{WRITE_URL}/{row.get('variety') or 'normal'}/{row['order_id']}"}

    def written_order_id(self, response):
        data = (response or {}).get("data")
        return text(data.get("order_id")) if isinstance(data, dict) else None
