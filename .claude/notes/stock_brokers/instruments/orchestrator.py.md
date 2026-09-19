# Notes on `stock_brokers/instruments/orchestrator.py`

## `INGESTERS`

`INGESTERS` lists all ten brokers, Stoxkart included. Stoxkart's instrument master is a public file that needs no login, so it was downloaded every day even while Stoxkart's API login did not work. That login has worked since commit 7da8cef on 2026-09-15, when it moved to Stoxkart's version 2 login, so the entry no longer needs any special explanation: Stoxkart is ingested like every other broker.

An earlier comment above `INGESTERS` said Stoxkart's API login was broken. It was removed on 2026-09-19 because it had become untrue, and its content moved here under the project rule that code files carry no explanatory comments.
