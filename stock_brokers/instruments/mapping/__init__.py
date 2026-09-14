"""
Cross-broker instrument mapping.

This package reads the raw broker instrument tables that ``stock_brokers/instruments/`` populates
daily - ``zerodha.instruments``, ``dhan.instruments`` and the other eight, one per broker schema -
and resolves every row into the two unified tables, ``unified.instruments`` and
``unified.broker_mappings``.

An instrument's identity is computed rather than matched. Each adapter hashes the composite natural
key ``(exchange, segment, shape, identity fields)`` to a UUID5 under one fixed namespace, so two
brokers carrying the same contract arrive at the same ``instrument_id`` independently and the
upsert converges them with no lookup step. ISIN and broker tokens are classification aids only,
never merge keys.

A note on the name, since it reads ambiguously in a sentence: ``instruments`` is both this Python
package's parent (``stock_brokers.instruments``) and the PostgreSQL schema the two unified tables
live in (``unified.instruments``). They never occupy the same syntactic position, but a bare
``instruments`` in prose is worth reading twice. The per-broker raw tables invert the pair, being a
table called ``instruments`` inside a schema named for the broker.
"""
