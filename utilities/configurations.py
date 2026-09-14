"""
Configuration read from the environment, and the shared clients built from it.

The connection helpers live beside the settings they read rather than in a module of their own:
there is one source of truth for where Redis, MongoDB and TimescaleDB are, and one place that
opens them.
"""

import os
import logging

import redis
import pymongo
import psycopg2
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

redis_configuration = {
    'host': os.getenv('UNIFIED_BROKER_INTERFACE_REDIS_HOST'),
    'port': int(os.getenv('UNIFIED_BROKER_INTERFACE_REDIS_PORT')),
    'db': int(os.getenv('UNIFIED_BROKER_INTERFACE_REDIS_DB')),
    'username': os.getenv('UNIFIED_BROKER_INTERFACE_REDIS_USERNAME'),
    'password': os.getenv('UNIFIED_BROKER_INTERFACE_REDIS_PASSWORD')
}

mongodb_configuration = {
    'host': os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_HOST'),
    'port': int(os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_PORT')),
    'db': os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_DB'),
    'username': os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_USERNAME'),
    'password': os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_PASSWORD'),
    'connection_string': f"mongodb://{os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_USERNAME')}:{os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_PASSWORD')}@{os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_HOST')}:{os.getenv('UNIFIED_BROKER_INTERFACE_MONGODB_PORT')}/"
}

postgres_configuration = {
    'host': os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_HOST'),
    'port': int(os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_PORT')),
    'db': os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_DB'),
    'username': os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_USERNAME'),
    'password': os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_PASSWORD'),
    'connection_string': f"postgresql://{os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_USERNAME')}:{os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_PASSWORD')}@{os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_HOST')}:{os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_PORT')}/{os.getenv('UNIFIED_BROKER_INTERFACE_POSTGRES_DB')}"
}

# The REST API's own settings. Unlike the stores above these are optional, so a script that never
# serves the API does not need them set.
api_configuration = {
    'host': os.getenv('UNIFIED_BROKER_INTERFACE_API_HOST', '127.0.0.1'),
    'port': int(os.getenv('UNIFIED_BROKER_INTERFACE_API_PORT', '8080')),
    'token_ttl_seconds': int(os.getenv('UNIFIED_BROKER_INTERFACE_API_TOKEN_TTL_SECONDS', '86400'))
}

logging.basicConfig(format='%(asctime)s %(levelname)-8s %(name)s %(message)s', level=logging.INFO, datefmt="%Y-%m-%d %H:%M:%S")

def get_cache():
    """
    Redis client shared by the broker API classes and scripts.

    `health_check_interval` makes redis-py ping a connection that has been idle for longer than
    thirty seconds before handing it back, which matters for the long running scripts: one that
    holds a connection across a quiet spell, overnight say, would otherwise only discover a dropped
    connection on its next command.

    Deliberately no `socket_timeout`: a blocking stream read (`XREADGROUP` with `block`) would then
    raise whenever it waited longer than the timeout. Stream readers bound their waiting with the
    read's own `block` instead.
    """
    return redis.Redis(host=redis_configuration['host'], port=redis_configuration['port'], username=redis_configuration['username'], password=redis_configuration['password'], db=redis_configuration['db'], decode_responses=True, encoding='utf-8', health_check_interval=30, socket_keepalive=True)

def get_mongo_db():
    """
    MongoDB database shared by the broker API classes and scripts.
    """
    mongo_client = pymongo.MongoClient(mongodb_configuration['connection_string'])
    return mongo_client[mongodb_configuration['db']]

def get_logger(name):
    """
    Named logger.

    - `name` is the name of the logger, for example `zerodha.quotes`.
    """
    return logging.getLogger(name)

def get_postgres():
    """
    TimescaleDB connection used by the tick persistence layer.
    """
    return psycopg2.connect(host=postgres_configuration['host'], port=postgres_configuration['port'],
                            dbname=postgres_configuration['db'], user=postgres_configuration['username'],
                            password=postgres_configuration['password'])

def get_postgres_engine():
    """
    SQLAlchemy engine over the same TimescaleDB the persisters write to.

    `get_postgres` returns a psycopg2 connection, which is what the tick, order and position
    persisters want because they COPY a fixed, known column list. The instrument loader instead
    writes whatever columns a broker published that day, straight off a pandas DataFrame, and
    `DataFrame.to_sql` needs an engine. The DDL runner uses it too.
    """
    return create_engine(postgres_configuration['connection_string'])
