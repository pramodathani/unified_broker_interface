-- One PostgreSQL schema per broker, ten in all, holding that broker's own tables: its instrument
-- snapshots, its price history and, for the nine brokers that stream, its live stream tables.
-- Stoxkart has no streaming tables, because its API login is broken, but its instrument master is a
-- public file that needs no login at all, so it gets a schema too.

CREATE SCHEMA IF NOT EXISTS zerodha;
CREATE SCHEMA IF NOT EXISTS dhan;
CREATE SCHEMA IF NOT EXISTS flattrade;
CREATE SCHEMA IF NOT EXISTS shoonya;
CREATE SCHEMA IF NOT EXISTS fyers;
CREATE SCHEMA IF NOT EXISTS groww;
CREATE SCHEMA IF NOT EXISTS kotak;
CREATE SCHEMA IF NOT EXISTS indmoney;
CREATE SCHEMA IF NOT EXISTS wisdom_capital;
CREATE SCHEMA IF NOT EXISTS stoxkart;
