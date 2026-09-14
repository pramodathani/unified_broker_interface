"""
Loading the three read-only detail collections the REST API serves from MongoDB Compass exports.

| Collection | Export file | Keyed by |
| --- | --- | --- |
| `exchange_details` | `unified_broker_interface.exchanges.json` | `exchange` |
| `broker_details` | `mongo_backup/unified_broker_interface.brokers.json` | `broker_name` |
| `user_details` | `unified_broker_interface.user_details.json` | nothing |

The exports' documents need two corrections on the way in.

**Exchanges** have no key the rest of this project uses, only a display `short_name` such as `NSE`.
Each document gains `exchange`, the lowercase code (`nse`, `bse`, `mcx`, `ncdex`) used everywhere
else, including `unified.instruments`.

**Brokers** are keyed by a misspelt `borker_name` holding a display name such as
`Kotak Neo (Kotak Securities Limited)`. That value is kept as `name`, and `broker_name` becomes the
project's broker code, `kotak`, through the explicit map below. A display name the map does not
know stops the import rather than guessing a code.

Exchanges and brokers are upserted on their keys under a unique index, so the import can be re-run
safely. Their fields are set rather than the documents replaced, so an exchange's trading hours and
holidays, copied in by `exchange_calendar`, survive a re-import. User profiles have no natural key, so they are loaded only into an empty collection unless
`replace` is asked for, which empties it first. The exports' `_id` values are dropped either way
and MongoDB assigns new ones.

The export files are read where they are and never copied into the repository: `user_details`
holds identity documents and bank account numbers.
"""

from pathlib import Path

from bson import json_util

from unified_broker_interface.utilities.broker_quotes.utilities.clients import API_CLASSES

EXCHANGES_FILE = 'unified_broker_interface.exchanges.json'
BROKERS_FILE = Path('mongo_backup') / 'unified_broker_interface.brokers.json'
USER_DETAILS_FILE = 'unified_broker_interface.user_details.json'

# Each broker's display name in the exports, and this project's code for it.
BROKER_CODES = {
    'dhan': 'dhan',
    'flattrade': 'flattrade',
    'fyers': 'fyers',
    'Groww': 'groww',
    'INDstocks': 'indmoney',
    'Kotak Neo (Kotak Securities Limited)': 'kotak',
    'Shoonya (Finvasia)': 'shoonya',
    'Stoxkart': 'stoxkart',
    'Wisdom Capital': 'wisdom_capital',
    'Zerodha': 'zerodha',
}

class DetailsImportError(Exception):
    """
    An export that cannot be loaded as it stands.
    """

def read_export(path):
    """
    The documents in a Compass JSON export, without their `_id`.

    - `path` is the export file.
    """
    documents = json_util.loads(Path(path).read_text())
    if isinstance(documents, dict):
        documents = [documents]
    for document in documents:
        document.pop('_id', None)
    return documents

def normalise_exchange(document):
    """
    An exchange document with its `exchange` code added from `short_name`.

    - `document` is an exchange document from the export.
    """
    short_name = document.get('short_name')
    if not short_name:
        raise DetailsImportError(f"exchange document without short_name: {document.get('name')!r}")
    return {'exchange': short_name.strip().lower(), **document}

def normalise_broker(document):
    """
    A broker document with its display name moved to `name` and `broker_name` set to the code.

    - `document` is a broker document from the export.
    """
    document = dict(document)
    display_name = document.pop('borker_name', None) or document.pop('broker_name', None)
    code = BROKER_CODES.get(display_name)
    if code is None:
        raise DetailsImportError(f"no broker code for the display name {display_name!r}")
    if code not in API_CLASSES:
        raise DetailsImportError(f"broker code {code!r} is not a broker this project supports")
    return {'broker_name': code, 'name': display_name, **document}

def _check_unique(collection_name, key, documents):
    """
    Refuse an export in which two documents share a key.

    - `collection_name` is the collection the documents are for, used in the message.
    - `key` is the field that identifies a document.
    - `documents` are the documents to check.
    """
    keys = [document[key] for document in documents]
    duplicates = sorted({value for value in keys if keys.count(value) > 1})
    if duplicates:
        raise DetailsImportError(f"{collection_name}: duplicate {key} in the export: {', '.join(duplicates)}")

def _upsert_all(collection, key, documents):
    """
    Insert each document, or set its fields on the document already there, under a unique index on
    its key.

    Fields are set rather than the document replaced, so what other steps add to a document - an
    exchange's copied trading hours and holidays - survives a re-import. Returns the number of
    documents newly inserted.

    - `collection` is the MongoDB collection.
    - `key` is the field that identifies a document.
    - `documents` are the documents to write.
    """
    collection.create_index(key, unique=True)
    inserted = 0
    for document in documents:
        result = collection.update_one({key: document[key]}, {'$set': document}, upsert=True)
        inserted += 1 if result.upserted_id is not None else 0
    return inserted

def import_details(mongo_db, export_directory, replace=False):
    """
    Load all three detail collections from a directory of exports.

    Everything is read and normalised before anything is written, so a bad document leaves the
    database untouched. Returns one line per collection describing what was done.

    - `mongo_db` is the MongoDB database to load into.
    - `export_directory` is the directory holding the export files.
    - `replace` empties `user_details` before loading it, instead of skipping a non-empty one.
    """
    directory = Path(export_directory)
    exchanges = [normalise_exchange(document) for document in read_export(directory / EXCHANGES_FILE)]
    brokers = [normalise_broker(document) for document in read_export(directory / BROKERS_FILE)]
    users = read_export(directory / USER_DETAILS_FILE)
    _check_unique('exchange_details', 'exchange', exchanges)
    _check_unique('broker_details', 'broker_name', brokers)

    report = []

    inserted = _upsert_all(mongo_db['exchange_details'], 'exchange', exchanges)
    report.append(f"exchange_details  {len(exchanges)} upserted ({inserted} new)")

    inserted = _upsert_all(mongo_db['broker_details'], 'broker_name', brokers)
    report.append(f"broker_details    {len(brokers)} upserted ({inserted} new)")

    user_details = mongo_db['user_details']
    existing = user_details.count_documents({})
    if existing and not replace:
        report.append(f"user_details      skipped: already holds {existing} document(s); use --replace")
    else:
        if existing:
            user_details.delete_many({})
        if users:
            user_details.insert_many(users)
        report.append(f"user_details      {len(users)} inserted"
                      + (f" (replaced {existing})" if existing else ""))
    return report
