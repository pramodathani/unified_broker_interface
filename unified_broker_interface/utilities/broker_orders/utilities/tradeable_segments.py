"""The exchanges and segments orders are sent for, with each segment's shape and asset class."""


class TradeableSegments:
    """The exchanges and bare segment names that `POST /api/orders/place` sends orders for.

    Attributes:
        EXCHANGES (list): The exchanges orders are sent for.
        SHAPES (dict): Each tradeable bare segment name to its shape: `security`, `future` or `option`.
        ASSET_CLASSES (dict): Each tradeable bare segment name to the asset class a broker's market table is keyed by.
    """

    EXCHANGES = [
        'nse',
        'bse',
    ]

    SHAPES = {
        'equities': 'security',
        'equity_futures': 'future',
        'equity_options': 'option',
        'equity_index_futures': 'future',
        'equity_index_options': 'option',
        'fixed_income': 'security',
        'fixed_income_futures': 'future',
        'fixed_income_options': 'option',
        'fixed_income_index_futures': 'future',
        'fixed_income_index_options': 'option',
        'exchange_traded_funds': 'security',
        'investment_trusts': 'security',
        'mutual_funds': 'security',
    }

    ASSET_CLASSES = {
        'equities': 'securities',
        'equity_futures': 'securities',
        'equity_options': 'securities',
        'equity_index_futures': 'securities',
        'equity_index_options': 'securities',
        'fixed_income': 'securities',
        'fixed_income_futures': 'securities',
        'fixed_income_options': 'securities',
        'fixed_income_index_futures': 'securities',
        'fixed_income_index_options': 'securities',
        'exchange_traded_funds': 'securities',
        'investment_trusts': 'securities',
        'mutual_funds': 'securities',
    }
