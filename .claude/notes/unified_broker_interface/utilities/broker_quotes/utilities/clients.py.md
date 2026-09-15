# Notes on `unified_broker_interface/utilities/broker_quotes/utilities/clients.py`

## `LOGIN_UNITS`

`LOGIN_UNITS` maps each broker that has a `<broker>-login.service` unit to that unit's name, so a worker that finds a broker's session dead can ask systemd to log it in. A broker missing from the map is never logged in from here; `request_login` logs a warning and returns.

Until 2026-09-15 a comment above the map said Stoxkart had no login unit yet. `services/stoxkart/stoxkart-login.service` was added that day, so Stoxkart joined the map and the comment was removed.
