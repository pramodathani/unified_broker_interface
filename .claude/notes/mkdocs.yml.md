# mkdocs.yml

## `returns_named_value: false`

Docstrings in this project write `Returns:` followed by a type and a description, such as `pandas.DataFrame: ...`. That is a type, not a named value. Without `returns_named_value: false`, griffe reads the type as a name and then warns that the return has no type, and `mkdocs build --strict` turns that warning into a build failure.

## Charts

`mkdocs-charts-plugin` renders ```` ```vegalite ```` fences as Vega-Lite charts. The vega, vega-lite and vega-embed scripts are loaded from jsDelivr through `extra_javascript`, because the plugin does not bundle them. `vega_theme_light` and `vega_theme_dark` make the charts follow the Material palette toggle. The plugin renamed `vega_theme` to `vega_theme_light` and refuses to build with the old name.

## Palette

The primary colour is deep orange, as a nod to Zerodha's Kite Connect documentation, whose layout the REST API pages follow.

## `watch`

`unified_broker_interface` is watched along with `stock_brokers` and `utilities`, because `utilities/gen_ref_pages.py` generates reference pages for all three packages and `mkdocs serve` should reload when any of them changes.

## `site_url`, `repo_url` and `edit_uri`

The site is published on GitHub Pages at `https://pramodathani.github.io/unified_broker_interface/` by `.github/workflows/docs.yml`. `site_url` gives the pages their canonical address and lets MkDocs write a correct sitemap. `repo_url` puts a link to the GitHub repository in the header, and `edit_uri` together with the `content.action.edit` and `content.action.view` features adds "edit this page" and "view source" buttons that open the page's Markdown file on the `main` branch.
