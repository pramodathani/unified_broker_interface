"""Raises `CandleBlocked` when a firewall in front of the broker bans the client, rather than treating it as a throttle.

A throttle clears once requests slow down, but a ban such as Cloudflare's error 1015 in front of Fyers is extended by every further request. So a broker module that sees one raises `CandleBlocked`, and the candle download stops the broker instead of backing off and trying the next series. This program has a stand-in HTTP answer shaped like Cloudflare's ban page and a small classifier that tells it apart from an ordinary 429 throttle.

No request leaves the machine: the answers are canned.

Run it from the project root:

    python examples/stock_brokers/instruments/historical/base/CandleBlocked/example_1_firewall_ban.py
"""

from stock_brokers.instruments.historical.base import (
    CandleBlocked,
    CandleError,
    CandleThrottled,
)


class StandInResponse:
    """A stand-in for an HTTP response.

    Attributes:
        status_code (int): The HTTP status.
        text (str): The response body.
    """

    def __init__(self, status_code, text):
        """Holds a canned response.

        Args:
            status_code (int): The HTTP status.
            text (str): The response body.

        Returns:
            None: This method returns nothing.
        """
        self.status_code = status_code
        self.text = text


class RefusalClassifier:
    """Turns a refused HTTP response into the candle failure it stands for."""

    def check(self, response):
        """Raises the failure a refused response stands for.

        Args:
            response (StandInResponse): The response to check.

        Returns:
            None: This method returns nothing when the response is not a refusal.

        Raises:
            CandleBlocked: When a firewall has banned the client.
            CandleThrottled: When the broker asks for fewer requests.
        """
        if 'error code: 1015' in response.text:
            raise CandleBlocked(f'HTTP {response.status_code}: the firewall has banned this address')
        if response.status_code == 429:
            raise CandleThrottled(f'HTTP {response.status_code}: {response.text}')


class FirewallBanExample:
    """Checks a throttle and a ban and prints what each became.

    Attributes:
        classifier (RefusalClassifier): The classifier being shown.
        responses (list): The canned responses.
    """

    def __init__(self):
        """Builds the classifier and two canned refusals.

        Returns:
            None: This method returns nothing.
        """
        self.classifier = RefusalClassifier()
        self.responses = [
            StandInResponse(429, '{"s":"error","code":429,"message":"request limit reached"}'),
            StandInResponse(429, '<html><title>Access denied | api-t1.fyers.in</title>error code: 1015</html>'),
        ]

    def run(self):
        """Checks each response and prints the failure it raised.

        Returns:
            None: This method returns nothing.
        """
        for response in self.responses:
            try:
                self.classifier.check(response)
            except CandleBlocked as error:
                print(f'CandleBlocked: {error}; stop this broker and send nothing more')
            except CandleThrottled as error:
                print(f'CandleThrottled: {error}; back off and carry on')
        print(f'CandleBlocked is a CandleError: {issubclass(CandleBlocked, CandleError)}')
        print(f'CandleBlocked is a kind of throttle: {issubclass(CandleBlocked, CandleThrottled)}')


if __name__ == '__main__':
    FirewallBanExample().run()
