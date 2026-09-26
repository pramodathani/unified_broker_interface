"""
A `POST` body naming several instruments for the instrument routes, and the result entries it is answered with.

The body is a JSON object whose `instruments` list names each instrument with the same fields the `GET` form takes in its query string: `instrument_id`, or `exchange`, `segment` and the segment's identity fields. Every other key in the body is a parameter shared by all the instruments, such as `date`, `interval` or `start`, spelled as in the query string. JSON numbers and booleans are accepted wherever the query string takes text, so `"strike_price": 25000` and `"adjusted": false` work.

An item that names no instrument properly gets its own 400 entry in the answer, and the other items are still answered. A body that is not an object, a missing or empty list, or a list longer than MAX_BATCH_INSTRUMENTS is refused as a whole.

Typical usage:

    batch = InstrumentBatch(request.get_json(silent=True))
    answers = catalogue.details_many(batch.valid_instruments(), parse_date(batch.parameters.get('date'), 'date'))
    return jsonify({'results': batch.results(answers)}), 200
"""

from unified_broker_interface.utilities.instrument_identity import RequestError, parse_instrument

MAX_BATCH_INSTRUMENTS = 50


class InstrumentBatch:
    """
    One batch request: the instruments it names, in order, and the parameters they share.

    Attributes:
        instruments (list): One entry per item of `instruments`, in order: the InstrumentQuery it names, or the RequestError saying why it names none.
        parameters (dict): The shared parameters as text keyed by name, ready for the same parsers the query string goes through.
    """

    def __init__(self, body):
        """
        Read a request body.

        Args:
            body (Any): The body as `request.get_json(silent=True)` returned it, which is None when it is missing or not JSON.

        Returns:
            None: This method returns nothing.

        Raises:
            RequestError: When the body is not a JSON object, `instruments` is missing, not a list, empty or longer than MAX_BATCH_INSTRUMENTS, or a shared parameter is not text, a number or a boolean.
        """
        if not isinstance(body, dict):
            raise RequestError("the body must be a JSON object with an instruments list")
        items = body.get("instruments")
        if not isinstance(items, list) or not items:
            raise RequestError("instruments must be a non-empty list")
        if len(items) > MAX_BATCH_INSTRUMENTS:
            raise RequestError(f"instruments may hold at most {MAX_BATCH_INSTRUMENTS} entries, not {len(items)}")

        self.parameters = {}
        for name, value in body.items():
            if name != "instruments":
                self.parameters[name] = self.as_text(name, value)

        self.instruments = []
        for item in items:
            self.instruments.append(self.parse_item(item))

    def parse_item(self, item):
        """
        The instrument one item of the list names.

        Args:
            item (Any): The item as it was decoded from JSON.

        Returns:
            InstrumentQuery | RequestError: The instrument, or the error saying why the item names none.
        """
        if not isinstance(item, dict):
            return RequestError("each entry of instruments must be an object")
        try:
            fields = {}
            for name, value in item.items():
                fields[name] = self.as_text(name, value)
            return parse_instrument(fields)
        except RequestError as error:
            return error

    def as_text(self, name, value):
        """
        A JSON value as the query string would have spelled it.

        Args:
            name (str): The key the value was given under, used in the error message.
            value (Any): The value as it was decoded from JSON.

        Returns:
            str | None: The value as text, "true" or "false" for a boolean, or None for null.

        Raises:
            RequestError: When the value is an object or a list.
        """
        if value is None:
            return None
        if isinstance(value, bool):
            if value:
                return "true"
            return "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return value
        raise RequestError(f"{name} must be text, a number or true or false")

    def valid_instruments(self):
        """
        The instruments that were named properly, in order, leaving out the items that failed.

        Returns:
            list[InstrumentQuery]: The instruments to look up.
        """
        valid = []
        for instrument in self.instruments:
            if not isinstance(instrument, RequestError):
                valid.append(instrument)
        return valid

    def results(self, answers):
        """
        The result entries for the whole list, from the answers to the valid instruments.

        Args:
            answers (list): One answer per instrument of valid_instruments, in the same order: the answer dict, or the RequestError saying why that instrument could not be answered.

        Returns:
            list[dict]: One entry per item of the request, in order, each with `request_index`, `status`, and either `data` or `error`.
        """
        entries = []
        answer_position = 0
        for request_index, instrument in enumerate(self.instruments):
            if isinstance(instrument, RequestError):
                entries.append(self.entry(request_index, instrument))
            else:
                entries.append(self.entry(request_index, answers[answer_position]))
                answer_position = answer_position + 1
        return entries

    def entry(self, request_index, answer):
        """
        One result entry.

        Args:
            request_index (int): The item's position in the request's list.
            answer (dict | RequestError): The answer, or the error saying why there is none.

        Returns:
            dict: `{"request_index", "status", "data"}` for an answer, or `{"request_index", "status", "error"}` for an error.
        """
        if isinstance(answer, RequestError):
            return {
                "request_index": request_index,
                "status": answer.status,
                "error": answer.message,
            }
        return {
            "request_index": request_index,
            "status": 200,
            "data": answer,
        }
