"""What came back from one request to a broker, and what it means."""


class BrokerAnswer:
    """The outcome of one sent request, with the timing of the call.

    Attributes:
        OUTCOME_STATUSES (dict): Each outcome to the HTTP status the route answers with.
        outcome (str): `accepted`, `rejected` or `unknown`.
        order_id (str | None): The broker's order id, for an accepted order.
        status_message (str | None): Why the outcome is not `accepted`, or None.
        response_body (object): The broker's body, decoded as JSON when possible and otherwise its first 300 characters, or None when nothing came back.
        status_code (int | None): The broker's HTTP status, or None when nothing came back.
        sent_at (float): `time.perf_counter()` just before the request was sent.
        answered_at (float): `time.perf_counter()` just after it returned or failed.
    """

    OUTCOME_STATUSES = {
        'accepted': 200,
        'rejected': 422,
        'unknown': 504,
    }

    def __init__(self, sent_at):
        """Starts an answer whose outcome is not yet known.

        Args:
            sent_at (float): `time.perf_counter()` just before the request was sent.

        Returns:
            None: This method returns nothing.
        """
        self.outcome = 'unknown'
        self.order_id = None
        self.status_message = None
        self.response_body = None
        self.status_code = None
        self.sent_at = sent_at
        self.answered_at = sent_at

    def response_fields(self):
        """The broker's body when it is a JSON object.

        Returns:
            dict: The body, or an empty dictionary when it is not a JSON object.
        """
        if isinstance(self.response_body, dict):
            return self.response_body
        return {}

    def http_status(self):
        """The HTTP status the route answers with for this outcome.

        Returns:
            int: 200, 422 or 504.
        """
        return self.OUTCOME_STATUSES[self.outcome]

    def broker_milliseconds(self):
        """How long the broker call took.

        Returns:
            float: The time in milliseconds, rounded to three places.
        """
        return round((self.answered_at - self.sent_at) * 1000, 3)
