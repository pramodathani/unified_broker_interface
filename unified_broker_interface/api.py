"""
The Flask application: every blueprint mounted under `/api`.

Served by gunicorn through `wsgi.py` in normal use, via `bin/rest-api`. Running this module
directly starts Flask's development server instead.
"""

from flask import Flask, jsonify

from utilities.configurations import api_configuration
from unified_broker_interface.blueprints.session import session_bp
from unified_broker_interface.blueprints.users import users_bp
from unified_broker_interface.blueprints.brokers import brokers_bp
from unified_broker_interface.blueprints.exchanges import exchanges_bp
from unified_broker_interface.blueprints.instruments import instruments_bp
from unified_broker_interface.blueprints.portfolio import portfolio_bp
from unified_broker_interface.blueprints.orders import orders_bp

api = Flask(__name__)
api.register_blueprint(session_bp, url_prefix='/api/session')
api.register_blueprint(users_bp, url_prefix='/api/users')
api.register_blueprint(brokers_bp, url_prefix='/api/brokers')
api.register_blueprint(exchanges_bp, url_prefix='/api/exchanges')
api.register_blueprint(instruments_bp, url_prefix='/api/instruments')
api.register_blueprint(portfolio_bp, url_prefix='/api/portfolio')
api.register_blueprint(orders_bp, url_prefix='/api/orders')

@api.route('/api/', methods=['GET'])
def home():
    """
    Greeting, needing no token, so a client can tell the API is up.
    """
    return jsonify({'message': 'Welcome to the Unified Broker Interface API'}), 200

if __name__ == '__main__':
    api.run(host=api_configuration['host'], port=api_configuration['port'])
