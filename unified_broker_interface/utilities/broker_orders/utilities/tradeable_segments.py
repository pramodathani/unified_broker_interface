"""The exchanges and segments orders are accepted for, with each segment's shape and asset class."""


class TradeableSegments:
    """The exchanges and bare segment names that `POST /api/orders/place` accepts orders for.

    Every segment in the mapping's vocabulary is here except the indices, which cannot be traded, and `uncategorised`, which does not say whether an instrument is a cash instrument or a derivative. Accepting a segment does not mean any broker takes it: each broker's `MARKETS` table lists the markets it has been confirmed for, and an order in any other market passes that broker over.

    Attributes:
        EXCHANGES (list): The exchanges orders are accepted for.
        SHAPES (dict): Each accepted bare segment name to its shape: `security`, `future` or `option`.
        ASSET_CLASSES (dict): Each accepted bare segment name to the asset class a broker's market table is keyed by: `securities`, `currency` or `commodity`.
    """

    EXCHANGES = [
        'nse',
        'bse',
        'mcx',
        'ncdex',
    ]

    SHAPES = {
        'fixed_income': 'security',
        'fixed_income_futures': 'future',
        'fixed_income_options': 'option',
        'fixed_income_index_futures': 'future',
        'fixed_income_index_options': 'option',
        'equities': 'security',
        'equity_futures': 'future',
        'equity_options': 'option',
        'equity_index_futures': 'future',
        'equity_index_options': 'option',
        'currencies': 'security',
        'currency_futures': 'future',
        'currency_options': 'option',
        'currency_index_futures': 'future',
        'currency_index_options': 'option',
        'commodities': 'security',
        'commodity_futures': 'future',
        'commodity_options': 'option',
        'commodity_index_futures': 'future',
        'commodity_index_options': 'option',
        'mutual_funds': 'security',
        'exchange_traded_funds': 'security',
        'investment_trusts': 'security',
    }

    ASSET_CLASSES = {
        'fixed_income': 'securities',
        'fixed_income_futures': 'securities',
        'fixed_income_options': 'securities',
        'fixed_income_index_futures': 'securities',
        'fixed_income_index_options': 'securities',
        'equities': 'securities',
        'equity_futures': 'securities',
        'equity_options': 'securities',
        'equity_index_futures': 'securities',
        'equity_index_options': 'securities',
        'currencies': 'currency',
        'currency_futures': 'currency',
        'currency_options': 'currency',
        'currency_index_futures': 'currency',
        'currency_index_options': 'currency',
        'commodities': 'commodity',
        'commodity_futures': 'commodity',
        'commodity_options': 'commodity',
        'commodity_index_futures': 'commodity',
        'commodity_index_options': 'commodity',
        'mutual_funds': 'securities',
        'exchange_traded_funds': 'securities',
        'investment_trusts': 'securities',
    }
