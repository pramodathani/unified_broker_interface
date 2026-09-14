"""
The gunicorn entry point: `gunicorn unified_broker_interface.wsgi:api`.
"""

from unified_broker_interface.api import api

__all__ = ['api']
