"""A request answered without calling a broker, and the builder for one."""


class RefusedRequestError(Exception):
    """A request the order routes answer without calling a broker.

    Attributes:
        body (dict): The JSON body of the answer.
        status (int): The HTTP status of the answer.
    """

    def __init__(self, body, status):
        """Builds the refusal.

        Args:
            body (dict): The JSON body of the answer.
            status (int): The HTTP status of the answer.

        Returns:
            None: This method returns nothing.
        """
        super().__init__(body.get('error'))
        self.body = body
        self.status = status

    @classmethod
    def refusal(cls, message, status, **fields):
        """Builds the refusal for a request answered without calling a broker.

        Args:
            message (str): The error message.
            status (int): The HTTP status.
            **fields (object): Other fields for the answer's body, such as `broker` or `skipped`.

        Returns:
            RefusedRequestError: The refusal, for the caller to raise.
        """
        body = {
            'error': message,
        }
        body.update(fields)
        return cls(body, status)
