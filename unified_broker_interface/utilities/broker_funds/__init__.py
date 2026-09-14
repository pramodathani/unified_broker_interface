"""
Funds and margin read live from each broker's REST API, for `/api/portfolio/funds`.

One module per broker calls that broker's funds endpoint and turns the response into a funds record in
one vocabulary - balances, profit and loss, margin blocked, the day's cash movement and a per-segment
breakdown - so the service can add every broker's record into one account. `base.py` defines what a
broker module provides and the record's shape; `utilities/` holds the service that asks every broker at
once.
"""
