"""One HTTP request to a broker, built but not yet sent."""


class BrokerRequest:
    """Everything needed to send one request to a broker, and to show it in a dry run.

    Attributes:
        method (str): The HTTP method.
        url (str): The URL.
        headers (dict): The session headers.
        params (dict | None): Query string parameters, or None.
        data (dict | str | None): A form body, as a dictionary or already encoded, or None.
        json_body (dict | None): A JSON body, or None.
        shown_form (dict | None): The form fields a dry run shows, or None when the body is JSON.
        verify_certificate (bool): Whether the broker's TLS certificate is checked.
        tag (str | None): The tag the broker receives, which for Groww is generated rather than the caller's.
    """

    def __init__(
        self,
        method,
        url,
        headers,
        params=None,
        data=None,
        json_body=None,
        shown_form=None,
        verify_certificate=True,
        tag=None,
    ):
        """Builds the request.

        Args:
            method (str): The HTTP method.
            url (str): The URL.
            headers (dict): The session headers.
            params (dict | None): Query string parameters.
            data (dict | str | None): A form body.
            json_body (dict | None): A JSON body.
            shown_form (dict | None): The form fields a dry run shows.
            verify_certificate (bool): Whether the broker's TLS certificate is checked.
            tag (str | None): The tag the broker receives.

        Returns:
            None: This method returns nothing.
        """
        self.method = method
        self.url = url
        self.headers = headers
        self.params = params
        self.data = data
        self.json_body = json_body
        self.shown_form = shown_form
        self.verify_certificate = verify_certificate
        self.tag = tag

    def shown(self):
        """The request as a dry run answers it: method, URL, parameters and body, without the session headers.

        Returns:
            dict: The request's method and URL, with `params`, and `form` or `json`, when present.
        """
        shown_request = {
            'method': self.method,
            'url': self.url,
        }
        if self.params is not None:
            shown_request['params'] = self.params
        if self.shown_form is not None:
            shown_request['form'] = self.shown_form
        elif self.json_body is not None:
            shown_request['json'] = self.json_body
        return shown_request
