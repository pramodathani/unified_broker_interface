"""
The REST API's access token: minting it, finding the one in force, and deciding whether a request's
token is acceptable.

There is one token for the whole application at a time, stored exactly the way a broker's login is:
a document keyed by `broker_name` in the MongoDB `last_login` collection, mirrored as JSON into the
Redis `last_login` hash under the same field. The application's `broker_name` is
`unified_broker_interface`, which keeps it apart from the ten broker logins beside it.

```json
{
  "broker_name": "unified_broker_interface",
  "access_token": "5b0c9d0e-8f7a-4c35-9a53-2f4f0f4f7a61",
  "last_login": "2026-09-13 16:02:11.402913",
  "expires_at": "2026-09-14 16:02:11.402913"
}
```

A connect hands back the token in force when it was issued at or after the most recent 07:00 and has
not expired or been revoked. Otherwise the connect mints a new token, which replaces the old one, so
the first connect after 07:00 each day ends the previous day's session. Disconnecting sets `access_token` to null, and a token is refused once `expires_at` has passed. A
document without `expires_at` - one written before tokens expired - is treated as expired.

MongoDB is the record and Redis the copy read on every request. Writes go to MongoDB first and
Redis second, the order the broker logins settled on. If the Redis write fails the field is deleted
instead, so the next read falls back to MongoDB rather than trusting a token that has since been
replaced or revoked.
"""

import hmac
import json
import uuid
from datetime import datetime, time, timedelta

from utilities.configurations import get_logger

# The `broker_name` of the application's own login document in `last_login`.
APP_NAME = 'unified_broker_interface'

COLLECTION = 'last_login'
CACHE_KEY = 'last_login'

# The timestamp format every login document in `last_login` uses.
TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

DAILY_RENEWAL_TIME = time(7, 0)

logger = get_logger('rest_api.tokens')

class TokenStore:
    """
    Reads and writes the application's login document.

    - `mongo_db` is the MongoDB database holding `settings` and `last_login`.
    - `cache` is the Redis client holding the `last_login` hash.
    """

    def __init__(self, mongo_db, cache):
        self._mongo_db = mongo_db
        self._cache = cache

    def current(self):
        """
        The login document in force, or None when there has never been one.

        Redis is read first. When it holds nothing, or cannot be reached, MongoDB is read and the
        document is written into Redis only if that field is still empty, so filling the cache can
        never overwrite a connect that lands in between.
        """
        try:
            raw = self._cache.hget(CACHE_KEY, APP_NAME)
            if raw:
                return json.loads(raw)
        except Exception as error:
            logger.warning(f"could not read the access token from Redis: {error}")

        document = self._mongo_db[COLLECTION].find_one({'broker_name': APP_NAME}, {'_id': 0})
        if document:
            try:
                self._cache.hsetnx(CACHE_KEY, APP_NAME, json.dumps(document))
            except Exception:
                pass
        return document

    def connect(self, ttl_seconds):
        """
        The login document a connecting client receives, and whether it was newly minted.

        Returns a pair `(document, issued)`. The stored token is returned unchanged, with `issued`
        False, when it was issued at or after the most recent 07:00 and is still accepted. Otherwise
        a new token replaces it and `issued` is True. The stored token is read from MongoDB, the
        record, rather than from its Redis copy.

        - `ttl_seconds` is how long a newly minted token is accepted for.
        """
        document = self._mongo_db[COLLECTION].find_one({'broker_name': APP_NAME}, {'_id': 0})
        if self._issued_today(document):
            return document, False
        return self.issue(ttl_seconds), True

    def issue(self, ttl_seconds):
        """
        Mint a new token, replacing whatever token was in force, and return its login document.

        - `ttl_seconds` is how long the token is accepted for.
        """
        now = datetime.now()
        document = {
            'broker_name': APP_NAME,
            'access_token': str(uuid.uuid4()),
            'last_login': now.strftime(TIME_FORMAT),
            'expires_at': (now + timedelta(seconds=ttl_seconds)).strftime(TIME_FORMAT)
        }
        self._store(document)
        return document

    def revoke(self):
        """
        End the session: the token in force stops being accepted immediately.
        """
        self._store({
            'broker_name': APP_NAME,
            'access_token': None,
            'last_login': datetime.now().strftime(TIME_FORMAT),
            'expires_at': None
        })

    def check(self, access_token):
        """
        Decide whether a request's token is acceptable.

        Returns a pair `(document, error)`. `document` is the login document when the token is
        accepted, and `error` is a message saying why it was refused otherwise.

        - `access_token` is the value of the request's `access-token` header, or None.
        """
        if not access_token:
            return None, 'Access token is required'

        document = self.current()
        stored_token = (document or {}).get('access_token')
        if not stored_token or not hmac.compare_digest(access_token.encode(), stored_token.encode()):
            return None, 'Invalid access token'

        expires_at = expiry_of(document)
        if expires_at is None or expires_at <= datetime.now():
            return None, 'Access token has expired'
        return document, None

    def _issued_today(self, document):
        """
        Whether a login document holds a live token issued at or after the most recent 07:00.

        Before 07:00 the most recent 07:00 is yesterday's, so a token issued after midnight is kept.

        - `document` is a login document from `last_login`, or None.
        """
        if not document or not document.get('access_token'):
            return False
        try:
            issued_at = datetime.strptime(document['last_login'], TIME_FORMAT)
        except (KeyError, TypeError, ValueError):
            return False

        now = datetime.now()
        renewal_at = datetime.combine(now.date(), DAILY_RENEWAL_TIME)
        if now < renewal_at:
            renewal_at = renewal_at - timedelta(days=1)

        expires_at = expiry_of(document)
        if expires_at is None or expires_at <= now:
            return False
        return issued_at >= renewal_at

    def _store(self, document):
        """
        Write a login document to MongoDB and then to Redis.

        - `document` is the login document to store.
        """
        self._mongo_db[COLLECTION].replace_one({'broker_name': APP_NAME}, document, upsert=True)
        try:
            self._cache.hset(CACHE_KEY, APP_NAME, json.dumps(document))
        except Exception as error:
            logger.warning(f"could not write the access token to Redis, clearing its copy: {error}")
            try:
                self._cache.hdel(CACHE_KEY, APP_NAME)
            except Exception:
                pass

def expiry_of(document):
    """
    When a login document's token expires, or None when it has no readable expiry.

    - `document` is a login document from `last_login`.
    """
    try:
        return datetime.strptime(document['expires_at'], TIME_FORMAT)
    except (KeyError, TypeError, ValueError):
        return None
