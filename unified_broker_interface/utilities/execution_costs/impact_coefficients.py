"""The square-root impact model's coefficient for each asset class, held from `unified.impact_coefficients`."""

from unified_broker_interface.utilities.broker_orders.utilities.tradeable_segments import (
    TradeableSegments,
)

READ_COEFFICIENTS = """
SELECT asset_class, coefficient, fitted_at
FROM unified.impact_coefficients
"""


class ImpactCoefficients:
    """Each asset class's coefficient, and whether it was fitted to real orders or is still the textbook value.

    The square-root model says an order of Q units in an instrument that trades V units a day, with daily volatility σ, moves the price by about Y × σ × √(Q ÷ V), and Y is this coefficient. Studies of many markets put Y near 1, which is what the table is seeded with; `fitted_at` stays empty until Y has been fitted to this project's own orders.

    Attributes:
        rows (dict): Each asset class (str) to a tuple of coefficient (decimal.Decimal) and fitted_at (datetime.datetime | None).
    """

    def __init__(self, rows=None):
        """Builds the coefficients.

        Args:
            rows (dict | None): Each asset class to a tuple of coefficient and fitted_at, or None for none yet.

        Returns:
            None: This method returns nothing.
        """
        self.rows = dict(rows or {})

    def load(self, cursor):
        """Reads every row of the table, replacing what was held.

        Args:
            cursor (psycopg2.extensions.cursor): An open cursor.

        Returns:
            int: How many rows were read.

        Raises:
            psycopg2.Error: When the table cannot be read.
        """
        cursor.execute(READ_COEFFICIENTS)
        rows = {}
        for asset_class, coefficient, fitted_at in cursor.fetchall():
            rows[asset_class] = (coefficient, fitted_at)
        self.rows = rows
        return len(rows)

    def asset_class(self, segment):
        """The asset class a segment belongs to.

        Args:
            segment (str | None): A segment such as `nse_equity_options`.

        Returns:
            str | None: `securities`, `currency` or `commodity`, or None for an unknown segment.
        """
        if not segment:
            return None
        _, _, bare_segment = segment.partition('_')
        return TradeableSegments.ASSET_CLASSES.get(bare_segment)

    def coefficient(self, segment):
        """The coefficient for a segment's asset class.

        Args:
            segment (str | None): A segment such as `nse_equity_options`.

        Returns:
            decimal.Decimal | None: The coefficient, or None when its asset class has no row.
        """
        row = self.rows.get(self.asset_class(segment))
        if row is None:
            return None
        return row[0]

    def is_fitted(self, segment):
        """Whether the coefficient for a segment's asset class was fitted to real orders.

        Args:
            segment (str | None): A segment such as `nse_equity_options`.

        Returns:
            bool: True when its row has a `fitted_at`.
        """
        row = self.rows.get(self.asset_class(segment))
        if row is None:
            return False
        return row[1] is not None
