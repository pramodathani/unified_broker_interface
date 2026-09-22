"""
What every blueprint is built from: its store connections, its route table, and the access token
check.
"""

import json
import functools

from flask import Blueprint, request, jsonify

from utilities.configurations import get_cache, get_mongo_db
from unified_broker_interface.utilities.tokens import TokenStore

def authenticated(fn):
    """
    Refuse the request with 401 unless its `access-token` header carries the token in force.

    Applied to every route except `POST /api/session/connect`, which authenticates with the api key
    and secret instead. The check uses the blueprint's own store connections rather than opening
    new ones for each request.

    - `fn` is a blueprint handler method.
    """
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        _, error = self.tokens.check(request.headers.get('access-token'))
        if error:
            return jsonify({'error': error}), 401
        return fn(self, *args, **kwargs)
    return wrapper

class BaseBlueprint:
    """
    A Flask blueprint declared as a class.

    A subclass sets `name` and `routes`, a list of `(url_rule, method_name, http_methods)`, and
    constructing it registers each route against the named method. The MongoDB database and Redis
    client are opened once per instance, and so once per gunicorn worker, since each blueprint
    module builds its instance on import.
    """
    name = None
    routes = []

    def __init__(self):
        self.blueprint = Blueprint(self.name, __name__)
        self.mongo_db = get_mongo_db()
        self.cache = get_cache()
        self.tokens = TokenStore(self.mongo_db, self.cache)
        for rule, handler_name, methods in self.routes:
            self.blueprint.add_url_rule(rule, view_func=getattr(self, handler_name), methods=methods)

    def collection_documents(self, collection, cache_key):
        """
        Every document in a collection without its `_id`: from its Redis copy, or from MongoDB when there is none.

        - `collection` is the name of the MongoDB collection.
        - `cache_key` is the Redis key `bin/unified/user/unified_details` caches it in, as a JSON array.

        A copy that is missing, unreadable or not an array falls back to MongoDB, the store of record, so the documents
        are served whether or not the cache is being kept.
        """
        try:
            value = self.cache.get(cache_key)
            documents = json.loads(value) if value is not None else None
        except Exception:
            documents = None
        if isinstance(documents, list):
            return documents
        return list(self.mongo_db[collection].find({}, {'_id': 0}))

    def list_collection(self, collection, cache_key, not_found_message):
        """
        Every document in a collection without its `_id`, or 404 when the collection is empty.

        - `collection` is the name of the MongoDB collection.
        - `cache_key` is the Redis key its copy is cached in.
        - `not_found_message` is the error returned when it holds nothing.
        """
        documents = self.collection_documents(collection, cache_key)
        if not documents:
            return jsonify({'error': not_found_message}), 404
        return jsonify(documents), 200
