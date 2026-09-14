"""
The unified broker interface REST API.

A Flask application that puts one HTTP interface in front of every broker this project supports.
A client first calls `POST /api/session/connect` with the api key and secret stored in the MongoDB
`settings` document for `unified_broker_interface`, receives an access token, and sends that token
in the `access-token` header of every other request.

- `api` builds the application and registers the blueprints.
- `wsgi` is the gunicorn entry point.
- `blueprints` holds one module per group of endpoints.
- `utilities` holds what the blueprints share: the access token store and the importer that loads
  the detail collections.
"""
