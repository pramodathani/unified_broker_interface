"""
What a broker's funds module provides, and the funds record every module fills in.

A module makes one call to its broker's funds or margin endpoint and adds what came back into a funds
record: the buckets `/api/portfolio/funds` answers with, all starting at zero. The service adds every
broker's record into one, so a field one broker does not report simply contributes nothing.

Every value goes through `number`, which reads a missing, blank or non-numeric field - including the
literal string "NaN" Wisdom Capital sends - as zero rather than letting it fail the whole broker.
"""

class FundsUnavailable(Exception):
    """
    The broker answered, but not with funds - an error carried in a successful response, or a body of
    the wrong shape.
    """

def number(value):
    """
    A broker's field as a float, or 0.0 when it is missing or not a number.

    - `value` is the field as the broker sent it.
    """
    if value is None:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed else 0.0

def funds_record():
    """
    An empty funds record: every bucket at zero and no segments.

    `total_balance` is not here, because no broker reports it; the service derives it from the sum.
    """
    return {
        "summary": {
            "available_balance": 0.0,
            "cash_balance": 0.0,
            "collateral_value": 0.0,
            "adhoc_credit": 0.0,
            "margin_utilized": 0.0,
            "withdrawable_balance": 0.0,
        },
        "pnl": {
            "realized": 0.0,
            "unrealized": 0.0,
        },
        "margin_breakdown": {
            "span_margin": 0.0,
            "exposure_margin": 0.0,
            "other_margin": 0.0,
        },
        "cash_movement": {
            "pay_in_today": 0.0,
            "pay_out_today": 0.0,
            "uncleared_funds": 0.0,
            "pending_withdrawal": 0.0,
        },
        "segments": {},
    }

def add(record, bucket, field, value):
    """
    Add a broker's field into one bucket of a funds record.

    - `record` is the funds record.
    - `bucket` is `summary`, `pnl`, `margin_breakdown` or `cash_movement`.
    - `field` is the field within that bucket.
    - `value` is the broker's value, read through `number`.
    """
    record[bucket][field] += number(value)

def add_segment(record, name, **fields):
    """
    Add a broker's figures into one segment of a funds record, creating the segment at zero first.

    - `record` is the funds record.
    - `name` is `equity`, `derivatives`, `currency` or `commodity`.
    - `fields` are any of `available_balance`, `margin_utilized`, `span_margin` and `exposure_margin`.
    """
    segment = record["segments"].setdefault(name, {
        "available_balance": 0.0,
        "margin_utilized": 0.0,
        "span_margin": 0.0,
        "exposure_margin": 0.0,
    })
    for field, value in fields.items():
        segment[field] += number(value)

class BrokerFundsSource:
    """
    Reads one broker's funds from its REST API as a funds record.

    Attributes:
        BROKER_NAME (str): The broker, as named in the `settings` collection.
        TIMEOUT_SECONDS (float): How long the broker may take to connect, and then to send each part of
            its answer, before the call is abandoned.
    """

    BROKER_NAME = None
    TIMEOUT_SECONDS = 5

    def fetch(self, client):
        """
        The broker's funds response, as its API client's `data`.

        - `client` is the broker's API client, whose `get`/`post` carry the session.

        Raises `FundsUnavailable` when the broker answered without funds, and lets the API client's own
        exceptions through.
        """
        raise NotImplementedError

    def normalize(self, data):
        """
        The funds record for what `fetch` returned.

        - `data` is the response `fetch` returned.
        """
        raise NotImplementedError

    def is_authentication_error(self, exception):
        """
        Whether an exception means the session is dead, so logging in again is the remedy.

        - `exception` is what `fetch` raised.
        """
        raise NotImplementedError
