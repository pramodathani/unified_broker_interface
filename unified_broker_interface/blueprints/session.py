"""
`/api/session`: exchanging the api key and secret for an access token, and ending the session.

The key and secret a client must present are the `api_key` and `api_secret` of the document whose
`broker_name` is `unified_broker_interface` in the MongoDB `settings` collection - the same
collection that holds each broker's credentials.
"""

import hmac

from flask import request, jsonify

from utilities.configurations import api_configuration, get_logger
from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated
from unified_broker_interface.utilities.tokens import APP_NAME

logger = get_logger('rest_api.session')

def _matches(supplied, stored):
    """
    Whether a supplied credential equals the stored one, compared in constant time.

    - `supplied` is the value from the request header, or None.
    - `stored` is the value from `settings`, or None.
    """
    if not supplied or not stored:
        return False
    return hmac.compare_digest(str(supplied).encode(), str(stored).encode())

class SessionBlueprint(BaseBlueprint):
    name = 'session'
    routes = [
        ('/connect', 'connect', ['POST']),
        ('/disconnect', 'disconnect', ['DELETE']),
        ('/status', 'status', ['GET']),
    ]

    def connect(self):
        """
        Return an access token for the `api-key` and `api-secret` request headers.

        The token stored in MongoDB is returned when it was issued at or after the most recent 07:00
        and is still accepted. Otherwise a new token is minted and stored, which replaces the old one,
        so any other client's session ends.
        """
        settings = self.mongo_db['settings'].find_one({'broker_name': APP_NAME}, {'_id': 0})
        if not settings:
            logger.error(f"no settings document for {APP_NAME}")
            return jsonify({'error': 'unified_broker_interface settings are not configured'}), 500

        key_matches = _matches(request.headers.get('api-key'), settings.get('api_key'))
        secret_matches = _matches(request.headers.get('api-secret'), settings.get('api_secret'))
        if not (key_matches and secret_matches):
            logger.warning(f"refused a connect from {request.remote_addr}: invalid api key or secret")
            return jsonify({'error': 'Invalid API key or secret'}), 401

        document, issued = self.tokens.connect(api_configuration['token_ttl_seconds'])
        if issued:
            logger.info(f"issued an access token to {request.remote_addr}, expiring {document['expires_at']}")
        else:
            logger.info(f"returned today's access token to {request.remote_addr}, expiring {document['expires_at']}")
        return jsonify({'access-token': document['access_token'], 'expires_at': document['expires_at']}), 200

    @authenticated
    def disconnect(self):
        """
        Revoke the access token in force.
        """
        self.tokens.revoke()
        return jsonify({'status': 'disconnected'}), 200

    @authenticated
    def status(self):
        """
        Report the session as connected, with when its token expires.
        """
        document = self.tokens.current()
        return jsonify({'status': 'connected', 'expires_at': document['expires_at']}), 200

session_bp = SessionBlueprint().blueprint
