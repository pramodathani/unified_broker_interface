# Project

This tab is for people who change UBI's code. It explains where everything lives, the one rule that shapes every package implemented once per broker, the full checklist for adding an eleventh broker, and how this documentation site is built.

<div class="grid cards" markdown>

-   :material-file-tree:{ .lg .middle } **Repository structure**

    ---

    An annotated tree of the repository, and which package is allowed to import which.

    [:octicons-arrow-right-24: Repository structure](structure.md)

-   :material-puzzle:{ .lg .middle } **Per-broker packages**

    ---

    Why every per-broker package holds only `__init__.py`, `base.py` and one file per broker, with class diagrams of the main hierarchies.

    [:octicons-arrow-right-24: Per-broker packages](per-broker-packages.md)

-   :material-plus-circle:{ .lg .middle } **Adding a broker**

    ---

    Every registry, list, DDL file, service and test that a new broker has to appear in, as an ordered checklist.

    [:octicons-arrow-right-24: Adding a broker](adding-a-broker.md)

-   :material-book-edit:{ .lg .middle } **Writing these docs**

    ---

    The MkDocs setup, the plugins, how to preview and build the site, and the visual conventions every page follows.

    [:octicons-arrow-right-24: Writing these docs](writing-docs.md)

</div>

## Ground rules for changes

A few rules apply to every change, whichever part of the code it touches. The list below collects them from the project's instructions and from the way the code is organized.

- **Broker traffic has a small number of homes.** The scripts in `bin/<broker>/` do almost all of it. Outside them, only the REST API's order routes, its quote fallback (used when no live quote is fresh) the order engine in `bin/unified/orders/order_engine`, and the hand-run tools `bin/check-broker-connections` and `bin/zerodha-quote` send requests to a broker. Every other unified script reads only the stores.
- **Each script is self-contained.** Pollers carry their own requests and normalization, with no shared poller base class, and a script's module docstring is its full reference.
- **Data is stored as the broker sent it.** The broker's untouched payload is kept beside the normalized one (`data` in Redis, `raw` in the database), and nothing is corrected or dropped on the way in.
- **Schemas live only in numbered `.sql` files**, and every statement must be safe to run again.
- **Docs change in the same commit as the code.** The code reference is generated from docstrings, so a docstring is documentation too.
- **Run the offline suites** in [Offline tests](../operations/tests.md) before and after a change, and check that `ruff check .` reports no more than its baseline of 41 findings.
