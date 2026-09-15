"""What a place request and a cancel request share: the error for an invalid request and the reading of true-or-false fields."""


class InvalidOrderError(ValueError):
    """A request body or query string that is not a valid order or cancel; its message is answered with HTTP 400."""


class OrderRequest:
    """The base of a validated order route request.

    Attributes:
        TRUE_SPELLINGS (list): The lower-case texts read as true.
        FALSE_SPELLINGS (list): The lower-case texts read as false.
    """

    TRUE_SPELLINGS = [
        'true',
        '1',
        'yes',
    ]

    FALSE_SPELLINGS = [
        'false',
        '0',
        'no',
        '',
    ]

    def parse_flag(self, field_name, raw_value):
        """Reads a true-or-false field that may arrive as a JSON boolean or as text.

        Args:
            field_name (str): The field's name, for the error message.
            raw_value (object): The value as received, or None when the field is absent.

        Returns:
            bool: The flag, False when the field is absent.

        Raises:
            InvalidOrderError: When the value is neither true nor false.
        """
        if raw_value is None:
            return False
        if isinstance(raw_value, bool):
            return raw_value
        spelling = str(raw_value).strip().lower()
        if spelling in self.TRUE_SPELLINGS:
            return True
        if spelling in self.FALSE_SPELLINGS:
            return False
        raise InvalidOrderError(f'{field_name} must be true or false')
