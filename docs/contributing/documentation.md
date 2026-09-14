# Writing docs

The site is [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/), built from
`docs/` in this repository. Docs live with the code so a change and its documentation travel in
the same commit.

```bash
mkdocs serve                  # http://127.0.0.1:8000, live reload
mkdocs build --strict         # what CI should run
```

The MkDocs packages are in `requirements.txt` alongside everything else, in a commented block at
the end.

`mkdocs.yml` watches `stock_brokers` and `utilities`, so editing a docstring rebuilds the
affected reference page too.

## Two kinds of page

**Narrative pages** are hand-written Markdown under `docs/`. They explain why something is shaped
the way it is, and how the pieces fit. They are listed explicitly in the `nav` in `mkdocs.yml`.

**Reference pages** are generated at build time by `utilities/gen_ref_pages.py`, one page per
module, straight from the docstrings. Nothing is written to disk in the project; `mkdocs-gen-files`
holds them in memory for the build, and the section's navigation is written to a
`reference/SUMMARY.md` that `mkdocs-literate-nav` reads.

A module added to `stock_brokers`, `unified_broker_interface` or `utilities` therefore appears in the
reference with no edit anywhere. Generated protocol buffer modules are excluded, being machine output with no
docstrings.

## Docstrings

The Python handler is configured for Google style. The existing docstrings mostly use a plainer
form - a summary line, then a bullet per parameter - and that renders fine; what matters is that
the summary says what the thing is and, where it is not obvious, why it is that way. The
project's better docstrings explain a decision rather than restating the signature, and those are
the ones worth imitating.

## Linking into the API reference

Cross-reference any documented object by its dotted path in square brackets:

```markdown
[`BrokerCandles`][stock_brokers.instruments.historical.base.BrokerCandles]
[`ingest_all`][stock_brokers.instruments.orchestrator.ingest_all]
```

Under `--strict` an unresolvable reference fails the build, which is what keeps these honest.

## Conventions used here

- **Admonitions** for asides: `!!! note`, `!!! tip`, `!!! warning`, and `!!! danger` reserved for
  anything that can place a live order or lose data.
- **Content tabs** (`=== "Label"`) for the same idea across brokers or variants, rather than
  repeating a section per broker.
- **Mermaid** fenced as ```` ```mermaid ```` for flow, sequence and class diagrams. No plugin is
  needed; the superfences configuration handles it.
- **Tables** for anything with more than three parallel facts. Keep the first column the name.

## Publishing

```bash
mkdocs gh-deploy
```

That builds the site and pushes it to a `gh-pages` branch, so the generated HTML never lands on
the source branch. `site/` is git-ignored for the same reason.
