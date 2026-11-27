#!/usr/bin/env python3
"""Validate every Bases view in the vault — the .base files and the inline
`base` blocks embedded in notes.

Read-only. It reports and never modifies, like the linter it sits beside.

What it checks, and why each one matters:

  1. YAML parses. A view with a syntax error opens as an error, not a table.
  2. `properties:` keys are prefixed. Obsidian IGNORES a bare key there and
     shows the raw property name as the column header, so the display name
     silently does nothing. This is the trap in `memory.base` and
     `stale.base` before they were repaired.
  3. Every `formula.X` referenced is DEFINED. A view that references an
     undefined formula fails silently — the column simply never appears.
  4. Every `sort` entry has an uppercase `direction`. A sort with any other
     value, or written as a string, is silently ignored.
  5. Every category a filter names EXISTS as a note under `Categories/`.
     `categories.contains(link("design"))` resolves against a real note; if
     the note is missing the filter matches nothing and the view is empty
     with no error anywhere.

Usage:
    python3 skills/vault-bases/check_bases.py
    python3 skills/vault-bases/check_bases.py --json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

VAULT = Path(__file__).resolve().parent.parent.parent


def find_categories_dir() -> Path | None:
    """The nearest `Categories/` folder at or above this script.

    The script sits in different places in the two trees — the vault's
    `skills/vault-bases/` and the published `agent-memory-commons/scripts/` —
    and in the published tree `Categories/` is a SIBLING of `scripts/`, not
    a child of the tree root. So the search starts at the script's own
    directory and walks up, which finds it in both layouts.
    """
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        cand = p / "Categories"
        if cand.is_dir():
            return cand
    return None


CATEGORIES_DIR = find_categories_dir() or (VAULT / "Categories")
SKIP_DIRS = {"node_modules", ".git", ".obsidian", ".venv", ".cache",
             "_archive", "_md-archive", "Attachments"}

VALID_DIRECTIONS = {"ASC", "DESC"}
VALID_PREFIXES = ("note.", "file.", "formula.")


def iter_markdown():
    for dp, dn, fn in os.walk(VAULT):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for name in fn:
            if name.lower().endswith((".md", ".markdown")):
                yield Path(dp) / name


def collect_views():
    """-> list of (label, text, source_path)."""
    views = []
    for p in sorted(VAULT.glob("*.base")) + sorted((VAULT / "Bases").glob("*.base")):
        views.append((p.relative_to(VAULT).as_posix(), p.read_text(encoding="utf-8"), p))
    pattern = re.compile(r"```base\n(.*?)```", re.S)
    for p in iter_markdown():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, m in enumerate(pattern.finditer(text), 1):
            views.append((f"{p.relative_to(VAULT).as_posix()} [inline #{i}]",
                          m.group(1), p))
    return views


def check_one(label: str, text: str) -> list[str]:
    problems = []
    try:
        doc = yaml.safe_load(text)
    except Exception as e:
        return [f"YAML does not parse: {e}"]
    if not isinstance(doc, dict):
        return ["not a mapping"]
    if "views" not in doc:
        problems.append("no `views:` — the file would open empty")

    formulas = set((doc.get("formulas") or {}).keys())

    for key in (doc.get("properties") or {}):
        if not key.startswith(VALID_PREFIXES):
            problems.append(
                f"properties key {key!r} has no prefix — Obsidian ignores the "
                f"display name and shows the raw property name")

    for v in doc.get("views") or []:
        name = v.get("name", "?")
        refs = list(v.get("order") or [])
        gb = v.get("groupBy") or {}
        if isinstance(gb, dict) and gb.get("property"):
            refs.append(gb["property"])
        for s in v.get("sort") or []:
            if not isinstance(s, dict):
                problems.append(f"view {name!r}: sort entry is not a mapping")
                continue
            d = s.get("direction")
            if d not in VALID_DIRECTIONS:
                problems.append(
                    f"view {name!r}: sort direction {d!r} is not ASC or DESC — "
                    f"the sort is silently ignored")
            if s.get("property"):
                refs.append(s["property"])
        for ref in refs:
            if isinstance(ref, str) and ref.startswith("formula."):
                if ref.split(".", 1)[1] not in formulas:
                    problems.append(
                        f"view {name!r}: {ref} is not defined in `formulas:` — "
                        f"the column silently never appears")

    for m in re.finditer(r'categories\.contains\(link\("([^"]+)"\)\)', text):
        cat = m.group(1)
        if not (CATEGORIES_DIR / f"{cat}.md").exists():
            problems.append(
                f"filter names category {cat!r} but Categories/{cat}.md does "
                f"not exist — the filter matches nothing")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    views = collect_views()
    results = []
    for label, text, _path in views:
        problems = check_one(label, text)
        results.append({"view": label, "problems": problems})

    bad = [r for r in results if r["problems"]]
    if args.json:
        print(json.dumps({"views": len(results), "results": results}, indent=2))
    else:
        for r in results:
            if r["problems"]:
                print(f"  BAD  {r['view']}")
                for p in r["problems"]:
                    print(f"        {p}")
            else:
                print(f"  OK   {r['view']}")
        print(f"\n{len(results)} view(s) checked, {len(bad)} with problems.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
