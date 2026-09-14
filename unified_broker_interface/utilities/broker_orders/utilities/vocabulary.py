"""
The shared vocabulary every broker's order terms are mapped onto, and the order contract they are mapped into.

Every broker describes the same order in its own words - `B`, `BUY_ORDER` or `1` for a buy, `TRADED`, `FILLED` or
`EXECUTED` for a complete order - and these tables map each spelling onto one vocabulary, so a client never branches
on which broker an order came from. `empty_order_update` is the order contract itself: every field present and unset,
filled in by each broker's module.
"""

import time

# Brokers describe the same order in wildly different vocabularies. These tables map each
# broker's spelling onto one shared vocabulary so that a consumer never has to branch on which
# broker an update came from. Keys are compared case insensitively.

TRANSACTION_TYPES = {
    "BUY": "BUY", "B": "BUY", "1": "BUY", "BUY_ORDER": "BUY",
    "SELL": "SELL", "S": "SELL", "-1": "SELL", "2": "SELL", "SELL_ORDER": "SELL",
}

PRODUCTS = {
    "CNC": "CNC", "C": "CNC", "DELIVERY": "CNC", "CASH": "CNC",
    "MIS": "MIS", "I": "MIS", "INTRADAY": "MIS", "M": "NRML",
    "NRML": "NRML", "NORMAL": "NRML", "MARGIN": "NRML", "CARRYFORWARD": "NRML",
    "CO": "CO", "BO": "BO", "MTF": "MTF", "ARB": "ARB",
    # Noren abbreviates products to a single letter: C cash, M margin, I intraday, H cover,
    # B bracket. "B" is a product here and a side in the transaction table - different tables,
    # so the letters do not collide.
    "H": "CO", "B": "BO",
}

ORDER_TYPES = {
    "MARKET": "MARKET", "MKT": "MARKET", "MKT ORDER": "MARKET", "2": "MARKET",
    "LIMIT": "LIMIT", "LMT": "LIMIT", "L": "LIMIT", "1": "LIMIT",
    "MKT": "MARKET",
    "SL": "SL", "SL-LMT": "SL", "STOPLIMIT": "SL", "SL LIMIT": "SL", "4": "SL",
    "SL-M": "SL-M", "SL-MKT": "SL-M", "STOPMARKET": "SL-M", "SL MARKET": "SL-M", "3": "SL-M",
    "SL M": "SL-M",
    # Dhan and Groww spell the stop-loss types out; the underscores are levelled to spaces before lookup.
    "STOP LOSS": "SL", "STOP LOSS MARKET": "SL-M",
}

VALIDITIES = {
    "DAY": "DAY", "EOS": "DAY", "0": "DAY",
    "IOC": "IOC", "IMMEDIATE": "IOC", "1": "IOC",
    "GTT": "GTT", "GTC": "GTC", "GTD": "GTD",
}

# The status vocabulary is the one that matters most: it is what a consumer branches on.
# Anything a broker sends that is not mapped here is passed through uppercased, so an unknown
# status is visible rather than silently collapsed into one of these.
STATUSES = {
    "PENDING": "PENDING", "TRANSIT": "PENDING", "VALIDATION PENDING": "PENDING",
    "PUT ORDER REQ RECEIVED": "PENDING", "TRIGGER PENDING": "PENDING", "AMO REQ RECEIVED": "PENDING",
    "PENDINGNEW": "PENDING",
    # INDstocks' order book marks an order not yet sent to the exchange - an after-market order - O-PENDING.
    "O-PENDING": "PENDING",
    "OPEN": "OPEN", "OPEN PENDING": "OPEN", "NEW": "OPEN", "REPLACED": "OPEN",
    "ACKED": "OPEN", "APPROVED": "OPEN", "MODIFICATION REQUESTED": "OPEN",
    "MODIFIED": "OPEN", "MODIFY VALIDATION PENDING": "OPEN", "MODIFY PENDING": "OPEN",
    "PARTIALLY FILLED": "OPEN", "PARTIALLY EXECUTED": "OPEN", "PLACED": "OPEN", "PART TRADED": "OPEN",
    # Symphony XTS writes these in CamelCase, which collapses without separators.
    "PARTIALLYFILLED": "OPEN", "PENDINGREPLACE": "OPEN",
    "CONFIRMED": "OPEN",
    "COMPLETE": "COMPLETE", "COMPLETED": "COMPLETE", "TRADED": "COMPLETE",
    "FILLED": "COMPLETE", "EXECUTED": "COMPLETE", "FULLY EXECUTED": "COMPLETE",
    "DELIVERY AWAITED": "COMPLETE",
    "CANCELLED": "CANCELLED", "CANCELED": "CANCELLED", "CANCEL": "CANCELLED",
    "CANCEL PENDING": "CANCELLED", "CANCELLATION REQUESTED": "CANCELLED",
    "PENDINGCANCEL": "CANCELLED",
    "CANCELLED AFTER MARKET ORDER": "CANCELLED",
    "REJECTED": "REJECTED", "REJECT": "REJECTED", "FAILED": "REJECTED",
    "EXPIRED": "EXPIRED",
}

def normalize(value, mapping):
    """
    Map a broker's own term onto the shared vocabulary.

    An unmapped value is returned uppercased rather than dropped, so that a term this project
    has not seen before shows up in the data instead of disappearing.

    - `value` is the broker's term.
    - `mapping` is one of the tables above.
    """
    if value is None or value == "":
        return None
    # Brokers separate words with spaces, underscores or hyphens for the same term, so the
    # separator is levelled before lookup rather than every spelling being listed.
    key = str(value).strip().upper().replace("_", " ")
    if key in mapping:
        return mapping[key]
    collapsed = " ".join(key.split())
    return mapping.get(collapsed, collapsed)

def empty_order_update(broker_name):
    """
    A normalized order update with every field present and unset.

    - `broker_name` is the name of the broker.
    """
    return {
        "broker": broker_name,
        "order_id": None,
        "exchange_order_id": None,
        "parent_order_id": None,
        "status": None,
        "status_message": None,
        "id": None,
        "instrument_token": None,
        "tradingsymbol": None,
        "exchange": None,
        "transaction_type": None,
        "product": None,
        "order_type": None,
        "validity": None,
        "quantity": None,
        "filled_quantity": None,
        "pending_quantity": None,
        "cancelled_quantity": None,
        "disclosed_quantity": None,
        "price": None,
        "trigger_price": None,
        "average_price": None,
        "order_timestamp": None,
        "exchange_timestamp": None,
        "tag": None,
        "raw": None,
        "received_at": time.time(),
    }
