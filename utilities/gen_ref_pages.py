"""
Builds the API reference pages from the source tree, at build time.

There is one page per module and the whole thing is generated, so a module added to
`stock_brokers`, `unified_broker_interface` or `utilities` appears in the reference without anyone
remembering to list it.
Nothing produced here is written to disk in the project: `mkdocs_gen_files` holds the pages in
memory for the duration of the build.

The navigation for the reference section is written to `reference/SUMMARY.md`, which the
literate-nav plugin reads. That is why `mkdocs.yml` says `- API reference: reference/` and not an
explicit list of pages.

This is build tooling rather than project code. It lives in `utilities` beside the other shared
helpers, and `mkdocs.yml` points the gen-files plugin at it by path - nothing imports it, and it
never runs outside a documentation build.
"""

from pathlib import Path

import mkdocs_gen_files

# Top level packages that get a reference section. A new one is added here.
PACKAGES = ("stock_brokers", "unified_broker_interface", "utilities")

# Generated protocol buffer modules are thousands of lines of machine output with no docstrings,
# and mkdocstrings on them produces pages nobody reads. This module is excluded too: it is part
# of the documentation build rather than part of the project being documented.
EXCLUDED_PARTS = ("__pycache__", "proto", "gen_ref_pages")

navigation = mkdocs_gen_files.Nav()
root = Path(__file__).parent.parent

for package in PACKAGES:
    for path in sorted((root / package).rglob("*.py")):
        module_path = path.relative_to(root).with_suffix("")
        if any(part in EXCLUDED_PARTS for part in module_path.parts):
            continue

        documentation_path = path.relative_to(root).with_suffix(".md")
        parts = tuple(module_path.parts)

        if parts[-1] == "__init__":
            parts = parts[:-1]
            documentation_path = documentation_path.with_name("index.md")
            # An empty package marker has nothing to render and no docstring to show.
            if not path.read_text().strip():
                continue
        elif parts[-1].startswith("__"):
            continue

        if not parts:
            continue

        navigation[parts] = documentation_path.as_posix()

        with mkdocs_gen_files.open(Path("reference") / documentation_path, "w") as page:
            print(f"::: {'.'.join(parts)}", file=page)

        mkdocs_gen_files.set_edit_path(Path("reference") / documentation_path, path.relative_to(root))

with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as summary:
    summary.writelines(navigation.build_literate_nav())
