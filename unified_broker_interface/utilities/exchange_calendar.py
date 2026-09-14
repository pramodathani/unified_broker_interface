"""
Copying each exchange's trading hours and holidays into its `exchange_details` document.

The data is copied, not referenced: after a copy each document carries its own `trading_hours`,
`holidays` and `special_sessions`, and the REST API returns them straight from MongoDB without
reading any file. A change to the sources therefore reaches the API only when the copy is run again,
which is what `import-api-details --calendars-only` is for.

**Holidays and special sessions** come from the yearly calendar files the tick pipeline uses,
`stock_brokers/instruments/ticks/utilities/calendars/<year>.yaml`, generated from each exchange's own
publication. Every year's file is read and merged, so a newly added year appears on the next copy.
Dates are stored as `YYYY-MM-DD` strings.

**Trading hours** are the sessions' real hours, from `TRADING_HOURS` below. They are not the
constants in `stock_brokers/instruments/ticks/utilities/sessions.py`: those are the wider windows the
tick pipeline accepts ticks in, opening at 09:00 for every segment and closing after the session to
keep closing prices. The hours here are the ones that module's comments state.

A copied exchange document gains:

```json
{
  "trading_hours": {
    "timezone": "Asia/Kolkata",
    "equity": {
      "pre_open": {"opens": "09:00", "closes": "09:15"},
      "sessions": [{"name": "normal", "opens": "09:15", "closes": "15:30"}]
    }
  },
  "holidays": {
    "equity": [{"date": "2026-01-26", "closed": "all", "name": "Republic Day"}]
  },
  "special_sessions": [
    {"date": "2026-11-08", "name": "Muhurat trading (timings to be notified)",
     "calendars": ["equity"], "opens": "09:00", "closes": "23:59:59"}
  ],
  "calendar_years": [2026],
  "calendar_copied_at": "2026-09-13 19:50:02.114210"
}
```

A calendar is the set of segments that close together: `equity` is cash, indices and equity
derivatives, `currency` is currency derivatives, and `commodity` is commodity derivatives. A holiday's
`closed` is `all`, or `morning` or `evening` for the commodity calendars, whose day splits into two
sessions at 17:00.
"""

from datetime import date, datetime
from pathlib import Path

import yaml

from stock_brokers.instruments.ticks.utilities.sessions import CALENDAR_DIRECTORY

COLLECTION = 'exchange_details'

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

CLOSURE_KINDS = ("all", "morning", "evening")

# NSE and BSE cash, index and equity derivatives trade 09:15-15:30, after a 09:00-09:15 pre-open.
_EQUITY_HOURS = {
    'pre_open': {'opens': '09:00', 'closes': '09:15'},
    'sessions': [{'name': 'normal', 'opens': '09:15', 'closes': '15:30'}],
}

# Currency derivatives trade 09:00-17:00.
_CURRENCY_HOURS = {
    'sessions': [{'name': 'normal', 'opens': '09:00', 'closes': '17:00'}],
}

# Commodity derivatives, on MCX and on the NSE and BSE commodity segments alike, trade a morning
# session 09:00-17:00 and an evening session 17:00-23:30, extended to 23:55 while the United States is
# on standard time.
_COMMODITY_HOURS = {
    'sessions': [
        {'name': 'morning', 'opens': '09:00', 'closes': '17:00'},
        {'name': 'evening', 'opens': '17:00', 'closes': '23:30', 'closes_during_us_standard_time': '23:55'},
    ],
}

# NCDEX trades a morning session 10:00-17:00 and an evening session 17:00-21:00.
_NCDEX_COMMODITY_HOURS = {
    'sessions': [
        {'name': 'morning', 'opens': '10:00', 'closes': '17:00'},
        {'name': 'evening', 'opens': '17:00', 'closes': '21:00'},
    ],
}

# Each exchange's calendars and their hours. The calendars listed are the ones whose holidays the
# calendar files publish for that exchange.
TRADING_HOURS = {
    'nse': {'equity': _EQUITY_HOURS, 'currency': _CURRENCY_HOURS, 'commodity': _COMMODITY_HOURS},
    'bse': {'equity': _EQUITY_HOURS, 'currency': _CURRENCY_HOURS, 'commodity': _COMMODITY_HOURS},
    'mcx': {'commodity': _COMMODITY_HOURS},
    'ncdex': {'commodity': _NCDEX_COMMODITY_HOURS},
}

TIMEZONE = 'Asia/Kolkata'

class CalendarCopyError(Exception):
    """
    Calendar data that cannot be copied as it stands.
    """

def _as_text(value):
    """
    A YAML date or time as the string stored in MongoDB.

    YAML reads an unquoted `2026-01-26` as a date, which MongoDB cannot store; it is written back in
    the same form.

    - `value` is the value read from YAML.
    """
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

def read_calendars(directory=CALENDAR_DIRECTORY):
    """
    Every year's holidays and special sessions, merged and grouped by exchange.

    Returns `(holidays, special_sessions, years)`. `holidays` maps exchange to calendar to a list of
    `{date, closed, name}` sorted by date. `special_sessions` maps exchange to a list of
    `{date, name, calendars, opens, closes}`. `years` lists the years read.

    - `directory` is the folder holding one `<year>.yaml` per year.
    """
    holidays, special_sessions, years = {}, {}, []
    paths = sorted(Path(directory).glob("*.yaml"))
    if not paths:
        raise CalendarCopyError(f"no calendar files in {directory}")

    for path in paths:
        document = yaml.safe_load(path.read_text()) or {}
        years.append(document.get("year"))
        for exchange, calendars in (document.get("holidays") or {}).items():
            for calendar, entries in (calendars or {}).items():
                for entry in entries or []:
                    if entry["closed"] not in CLOSURE_KINDS:
                        raise CalendarCopyError(
                            f"{path.name}: {exchange} {calendar} {entry['date']} closed is {entry['closed']!r}")
                    holidays.setdefault(exchange, {}).setdefault(calendar, []).append({
                        'date': _as_text(entry['date']),
                        'closed': entry['closed'],
                        'name': entry['name'],
                    })
        for entry in document.get("special_sessions") or []:
            for exchange in entry["exchanges"]:
                special_sessions.setdefault(exchange, []).append({
                    'date': _as_text(entry['date']),
                    'name': entry['name'],
                    'calendars': list(entry['calendars']),
                    'opens': _as_text(entry['opens']),
                    'closes': _as_text(entry['closes']),
                })

    for calendars in holidays.values():
        for entries in calendars.values():
            entries.sort(key=lambda entry: entry['date'])
    for entries in special_sessions.values():
        entries.sort(key=lambda entry: entry['date'])
    return holidays, special_sessions, sorted(year for year in years if year is not None)

def calendar_fields(exchange, holidays, special_sessions, years, copied_at):
    """
    The fields copied into one exchange's document.

    Only the calendars the exchange trades are kept, so MCX's document carries no equity holidays and
    a special session is narrowed to the calendars the exchange has.

    - `exchange` is the exchange code, such as `nse`.
    - `holidays`, `special_sessions` and `years` are what `read_calendars` returned.
    - `copied_at` is the time of the copy, as text.
    """
    hours = TRADING_HOURS[exchange]
    calendars = list(hours)

    sessions = []
    for session in special_sessions.get(exchange, []):
        kept = [calendar for calendar in session['calendars'] if calendar in calendars]
        if kept:
            sessions.append({**session, 'calendars': kept})

    return {
        'trading_hours': {'timezone': TIMEZONE, **hours},
        'holidays': {calendar: holidays.get(exchange, {}).get(calendar, []) for calendar in calendars},
        'special_sessions': sessions,
        'calendar_years': years,
        'calendar_copied_at': copied_at,
    }

def copy_exchange_calendars(mongo_db, directory=CALENDAR_DIRECTORY):
    """
    Write each exchange's trading hours, holidays and special sessions into `exchange_details`.

    Only these fields are set; the exchange's profile fields are left as they are. Every exchange in
    `TRADING_HOURS` must already have a document, since the profile is what the endpoint is for, and
    everything is read and checked before anything is written. Returns one report line per exchange.

    - `mongo_db` is the MongoDB database holding `exchange_details`.
    - `directory` is the folder holding the calendar files.
    """
    holidays, special_sessions, years = read_calendars(directory)

    unknown = sorted(set(holidays) - set(TRADING_HOURS))
    if unknown:
        raise CalendarCopyError(f"calendar files list exchanges with no trading hours: {', '.join(unknown)}")

    collection = mongo_db[COLLECTION]
    present = {document['exchange'] for document in collection.find({}, {'exchange': 1})}
    missing = sorted(set(TRADING_HOURS) - present)
    if missing:
        raise CalendarCopyError(f"{COLLECTION} has no document for: {', '.join(missing)}; import the exports first")

    copied_at = datetime.now().strftime(TIME_FORMAT)
    report = []
    for exchange in TRADING_HOURS:
        fields = calendar_fields(exchange, holidays, special_sessions, years, copied_at)
        collection.update_one({'exchange': exchange}, {'$set': fields})
        counts = ', '.join(f"{calendar} {len(entries)}" for calendar, entries in fields['holidays'].items())
        report.append(f"{exchange:<6} holidays: {counts}; special sessions: {len(fields['special_sessions'])}")
    return report
