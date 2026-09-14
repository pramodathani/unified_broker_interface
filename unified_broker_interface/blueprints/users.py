"""
`/api/users`: the account holder's profile - the MongoDB `user_details` collection, served from its Redis copy
`unified:details:users` when `bin/unified/details` keeps one, and every broker's own profile of the account from the
Redis key `unified:user:details`.
"""

import json

from flask import jsonify

from unified_broker_interface.blueprints.base import BaseBlueprint, authenticated

# Kept by bin/unified/user-profile: one object with a key per broker and that broker's profile, or null, as the value.
BROKER_PROFILES_KEY = 'unified:user:details'

class UsersBlueprint(BaseBlueprint):
    name = 'users'
    routes = [('/details', 'get_user_profile', ['GET'])]

    @authenticated
    def get_user_profile(self):
        """
        Every user profile document, and each broker's profile of the account.

        Returns `{"user_details": [...], "broker_profiles": {"dhan": {...}, "zerodha": {...}, ...}}`. `broker_profiles`
        is null when `unified:user:details` is missing or unreadable, so a Redis without it still serves the documents.
        404 when there is neither a document nor a profile.
        """
        documents = self.collection_documents('user_details', 'unified:details:users')
        broker_profiles = self.broker_profiles()
        if not documents and not any((broker_profiles or {}).values()):
            return jsonify({'error': 'User profile not found'}), 404
        return jsonify({'user_details': documents, 'broker_profiles': broker_profiles}), 200

    def broker_profiles(self):
        """The object in `unified:user:details`, or None when it is missing, unreadable or not an object."""
        try:
            value = self.cache.get(BROKER_PROFILES_KEY)
            profiles = json.loads(value) if value else None
        except Exception:
            return None
        return profiles if isinstance(profiles, dict) else None

users_bp = UsersBlueprint().blueprint
