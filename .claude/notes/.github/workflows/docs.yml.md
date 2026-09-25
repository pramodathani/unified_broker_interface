# .github/workflows/docs.yml

This workflow builds the MkDocs site and publishes it on GitHub Pages at `https://pramodathani.github.io/unified_broker_interface/`.

## When it runs

| Event | Build | Publish |
|---|:---:|:---:|
| Push to `main` (including a merged pull request) | Yes | Yes |
| Pull request | Yes | No |
| Started by hand from the Actions tab (`workflow_dispatch`) | Yes | Only when started on `main` |

Building on pull requests means `mkdocs build --strict` checks every change for broken links and unresolvable code references before it is merged. The `deploy` job's `if:` keeps a pull request from publishing an unmerged site.

## Why only the documentation packages are installed

The full `requirements.txt` pulls in the whole trading stack, including packages such as TA-Lib that need system libraries. The site does not need them: mkdocstrings reads the source files with griffe instead of importing them, and `utilities/gen_ref_pages.py` only walks the directory tree. The workflow therefore installs only the lines that start with `mkdocs` or `pymdown`, which are the eight pinned documentation packages. A clean virtual environment holding only those eight packages built the site with `--strict` on 2026-09-26, which confirmed this.

No Redis, MongoDB, PostgreSQL, `.env` or broker credential is needed, and none is available to the workflow.

## Permissions and concurrency

`pages: write` and `id-token: write` are what `actions/deploy-pages` needs to publish. `contents: read` is all the build needs. The `pages` concurrency group with `cancel-in-progress: false` lets a running deployment finish, rather than cancelling it halfway when a second push arrives.

## Repository setting

GitHub Pages must be set to deploy from GitHub Actions (Settings → Pages → Source: "GitHub Actions"). Without that, the `deploy` job fails.
