"""
IND Money instrument master ingestion.

IND Money is the only broker here whose master is not public. It serves three CSV files behind an Authorization header carrying an access token, which lasts twenty-four hours.

The token is read from the MongoDB ``last_login`` collection, where the broker login records it, so this module keeps no second copy of the token in the environment. A token issued on an earlier day is rejected rather than sent, because IND Money would only answer it with an authentication error that says nothing about the cause. When no usable token is stored, the ingester logs in itself through ``ensure_session`` rather than failing: the daily instrument download runs before the morning session refresh, so depending on that ordering would mean failing every weekday.
"""

from datetime import datetime
from io import StringIO

import pandas
import requests

from stock_brokers.instruments.base import BrokerInstruments
from utilities.configurations import get_mongo_db

INSTRUMENTS_URL = "https://api.indstocks.com/market/instruments"

SOURCES = [
    "equity",
    "fno",
    "index",
]

DOWNLOAD_TIMEOUT_SECONDS = 120


def stored_access_token():
    """
    Read today's IND Money access token from the MongoDB last_login collection.

    The daily broker login job writes one document per broker there, holding the token it received and the moment it received it. A token from an earlier day is not returned: IND Money's tokens last twenty-four hours, and sending a stale one produces an authentication error that says nothing about why.

    Returns:
        str | None: The token issued today, or None when there is no document, no token in it, or the token was issued on an earlier date.
    """
    document = get_mongo_db()["last_login"].find_one({"broker_name": "indmoney"})
    if document is None:
        return None
    last_login = document.get("last_login")
    if not last_login or last_login[:10] != datetime.now().strftime("%Y-%m-%d"):
        return None
    return document.get("access_token")


class IndMoneyInstruments(BrokerInstruments):
    """
    Downloads IND Money's daily instrument master.

    Attributes:
        BROKER_NAME (str): Always "indmoney".
        DEDUPE_KEY_COLUMNS (list[str]): Exchange, segment and security identifier together.
        DEDUPE_SORT_COLUMN (str | None): Series, so the kept row is predictable.
    """

    BROKER_NAME = "indmoney"
    DEDUPE_KEY_COLUMNS = [
        "exch",
        "segment",
        "security_id",
    ]
    DEDUPE_SORT_COLUMN = "series"

    def __init__(self, access_token=None):
        """
        Build the IND Money ingester.

        Args:
            access_token (str | None): Token to authenticate with. When omitted, today's token is read from the MongoDB last_login collection.
        """
        super().__init__()
        self.access_token = access_token or stored_access_token()

    def establish_session(self):
        """
        Log IND Money in and return the token that produces, or None.

        Called only when no usable token is already stored. Every other broker publishes its
        instrument master as a public file, so this is the one ingester whose success depends on
        a session, and the daily download runs before the morning login refresh - without this it
        would fail every weekday on a stale token and wait for somebody to notice.

        Goes through `ensure_session` rather than constructing the API class directly, so it
        shares the Redis lock and the rate limiter with any other process using `ensure_session`.
        IND Money issues one token per session, so a download logging in while another process does
        the same would otherwise leave one of them holding a replaced token.

        Returns:
            str | None: Today's token, or None when the login did not produce one.
        """
        from stock_brokers.api.utilities.session import SessionException, ensure_session

        try:
            ensure_session("indmoney")
        except SessionException as exception:
            print(f"indmoney: could not establish a session for the instrument download: "
                  f"{exception}")
            return None
        return stored_access_token()

    def download(self):
        """
        Fetch IND Money's three instrument master CSV files.

        Logs in first when no usable token is stored, since the endpoint rejects an
        unauthenticated request and a token issued on an earlier day is treated as absent.

        Returns:
            pandas.DataFrame: Every row IND Money published, read as text.

        Raises:
            ValueError: If no access token could be obtained.
            requests.HTTPError: If any of the three requests fails.
        """
        if not self.access_token:
            self.access_token = self.establish_session()

        if not self.access_token:
            raise ValueError(
                "No IND Money access token available, and logging in did not produce one. "
                "Try 'bin/indmoney/session/connect' and read the error it reports. The token lasts "
                "twenty-four hours, and one issued on an earlier day is not reused."
            )

        frames = []
        for source in SOURCES:
            response = requests.get(
                INSTRUMENTS_URL,
                params={"source": source},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self.access_token,
                },
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            frames.append(pandas.read_csv(StringIO(response.text), dtype=str))
        return pandas.concat(frames, ignore_index=True)
