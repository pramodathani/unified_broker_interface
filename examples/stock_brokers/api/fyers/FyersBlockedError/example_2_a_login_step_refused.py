"""Shows a login step refused with HTTP 429 raising `FyersBlockedError`, so the caller waits instead of starting another login.

A Fyers login is five requests: send the OTP, verify it, verify the PIN, get an auth code, and validate it. When any of them is refused with HTTP 429, `_refuse_if_blocked` raises `FyersBlockedError` naming the step, and the pollers recognise it as a ban and pause for thirty minutes. A step refused any other way still raises plain `FyersAPIException`, as before. This program checks three stand-in responses without sending anything.

Notice that only the 429 raises, and that its message names the step and mentions Cloudflare, which is what the pollers' `is_block` looks for.

Run it from the project root:

    python examples/stock_brokers/api/fyers/FyersBlockedError/example_2_a_login_step_refused.py
"""

from stock_brokers.api.fyers import (
    FyersAPI,
    FyersBlockedError,
)


class StandInResponse:
    """A response with a status and a body.

    Attributes:
        status_code (int): The HTTP status.
        text (str): The body.
    """

    def __init__(self, status_code, text):
        """Builds the response.

        Args:
            status_code (int): The HTTP status.
            text (str): The body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.text = text


class OfflineFyersAPI(FyersAPI):
    """A Fyers API object built without any store or request."""

    def __init__(self):
        """Builds nothing.

        Returns:
            None: This method returns nothing.
        """


class ALoginStepRefusedExample:
    """Checks three login-step responses.

    Attributes:
        api (OfflineFyersAPI): The API object.
    """

    def __init__(self):
        """Builds the API object.

        Returns:
            None: This method returns nothing.
        """
        self.api = OfflineFyersAPI()

    def run(self):
        """Prints what each response leads to.

        Returns:
            None: This method returns nothing.
        """
        responses = [
            ('OTP sent', StandInResponse(200, '{"request_key": "abc"}')),
            ('OTP refused by a ban', StandInResponse(429, '<html>error code: 1015</html>')),
            ('OTP refused for a wrong ID', StandInResponse(400, '{"s": "error"}')),
        ]
        for description, response in responses:
            try:
                self.api._refuse_if_blocked(response, 'Sending the login OTP')
                print(f'{description}: carries on to the next check')
            except FyersBlockedError as error:
                print(f'{description}: FyersBlockedError {error.args[0]}: {error.args[1][:90]}')


if __name__ == '__main__':
    ALoginStepRefusedExample().run()
