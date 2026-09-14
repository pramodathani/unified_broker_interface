# Installation

## Requirements

| Requirement | Version used here | Notes |
| --- | --- | --- |
| Python | 3.14 | The virtual environment in `.venv` is built against it |
| Redis | 6 or later | Queues and current state |
| MongoDB | 6 or later | Broker credentials and login tokens |
| PostgreSQL + TimescaleDB | 15 + TimescaleDB 2 | Ticks, order updates, positions, instruments |
| Google Chrome + chromedriver | current stable | Several brokers log in through Selenium |
| TA-Lib C library | 0.6 or later | `TA-Lib` in `requirements.txt` wraps it |

## The virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Import path

Modules import as `stock_brokers.…` and `utilities.…` from the project root, and there is no
`pyproject.toml` installing the packages, so the project root has to be on `PYTHONPATH`. The
`.env` file carries a `PYTHONPATH` entry for this, and running everything as a module from the
project root also works:

```bash
python -m stock_brokers.instruments.sql.apply_ddl
```

## The documentation toolchain

The MkDocs packages are in the same `requirements.txt`, in a commented block at the end, so the
install above already has them.

```bash
mkdocs serve
```

That serves the site at `http://127.0.0.1:8000` with live reload; `mkdocs.yml` watches
`stock_brokers` and `utilities`, so editing a docstring rebuilds the reference page too.

To produce the static site:

```bash
mkdocs build --strict
```

`--strict` turns broken internal links and unresolved references into build failures, which is
what CI should run.
