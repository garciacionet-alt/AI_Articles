#!/usr/bin/env python3
"""
lint.py — a read-only health check over the Agent Memory Commons.

Reports, and never modifies:

  1. dangling markdown links      — relative links that resolve to nothing
  2. dangling wikilinks           — [[slug]] with no matching file
  3. broken move pointers         — a moved-pointer stub whose target is gone
  4. orphan pages                 — nothing links to them
  5. frontmatter schema drift     — unknown `type:` values, missing fields
  6. stale markers                — notes flagged `status: stale`
  7. pending stubs                — move pointers cleanup has not yet removed
  8. uncommitted changes          — working tree vs git

Usage:
    python3 skills/memory-lint/lint.py              # full report
    python3 skills/memory-lint/lint.py --strict     # warnings become failures
    python3 skills/memory-lint/lint.py --quiet      # errors only
    python3 skills/memory-lint/lint.py --json       # machine-readable

Exit code 0 when clean, 1 when errors were found.

Strictly read-only: it opens files for reading and runs `git status`.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from urllib.parse import unquote

VAULT = os.path.expanduser("~/<vault>/projects")

# Tooling, dependency trees, raw logs and excluded confidential material —
# not vault content, and not linted.
#
# "skill_library" is a vendored drop of third-party skill packages (the Lark
# tool set, the PDF templates, and a copy of this linter). Three reasons it
# is skipped rather than patched:
#   - it is never committed to git; it is a local convenience copy
#   - every file in it shares one import mtime — it arrives wholesale
#   - its relative links are written against the upstream package layout, so
#     they resolve one level off from where the package sits inside the
#     vault. "Patching" them means editing a vendored copy that the next
#     import overwrites.
# Fixing the 13 dangling links this tree produced was the alternative; it
# was rejected as editing third-party content that is not ours to fix.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "__pycache__", ".obsidian",
    "restore", "_archive", "generated-media", "Consulting", "TensorMem",
    "artifacts", "outputs", "storage-downloads", "himalaya", "~",
    "skill_library",
}

# The wiki's own page types (wiki/schema.md).
WIKI_TYPES = {"entity", "concept", "source", "meta"}

# The vault-wide type vocabulary. Anything outside this is reported as drift.
#
# Reconciled 2026-11-24 against the measured usage. The list used to carry
# seven values no file ever used (`catalog`, `guide`, `mistake`, `pattern`,
# `context`, `snapshot`, and the format-like `status`/`todo`/`folder-readme`
# family) while MISSING four that files did use (`measurement`, `handoff`,
# `project`, `plan`). A closed vocabulary that is wrong in both directions
# is worse than an open one, because the linter then reports drift on the
# vault's own files.
#
# `moved-pointer` stays and is functional: the linter checks its `moved_to`
# target exists, which is how a retired path stays reachable.
VAULT_TYPES = {
    # AMC scope
    "design", "ops", "protocol", "index", "reference", "note", "log",
    "briefing", "work-instruction", "plan", "decision", "measurement",
    "handoff", "project", "publish-source", "newsletter",
    # Wiki scope
    "entity", "concept", "source", "meta", "moc",
    # A stub that points at the real file
    "moved-pointer",
}

# The status vocabulary: a lifecycle state, never a description. The Bases
# views sort and group on this field, so a sentence in it makes both views
# useless. "stale" is the pruning marker - set it and the note lands in the
# stale.base queue for human review.
#
# `retired` (an edition that was built and never shipped) and `ready`
# (staged and waiting on a human) were already in use and are now declared.
VAULT_STATUSES = {
    "maintained", "active", "draft", "done", "verified", "stale",
    "reference", "archived", "retired", "ready",
}

# The category vocabulary — the axis that crosses folder classes. Each
# category is a note under Categories/, so `categories.contains(link(...))`
# resolves. See CONVENTIONS.md §4.
VAULT_CATEGORIES = {
    "categories", "design", "ops", "publish", "reference", "newsletter",
    "handoff", "project", "agent",
}

# Frontmatter required on each wiki page type (wiki/schema.md).
WIKI_REQUIRED = {
    "entity": ["title", "type", "created", "updated", "tags"],
    "concept": ["title", "type", "created", "updated", "tags"],
    "source": ["title", "type", "created", "updated", "tags"],
    "meta": ["title", "type"],
}

MD_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
FENCE_LINE = re.compile(r"^\s*```")
INLINE_CODE = re.compile(r"`[^`\n]*`")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp")
PENDING_HEADING = re.compile(r"pending|not yet created|to be created|planned", re.I)

# Files that document the conventions and therefore contain example links
# on purpose. Their dangling links are reported as info, not errors.
DOC_FILES = {"wiki/schema.md", "wiki/README.md"}

# Publication sources. Their relative links are written as they will appear
# in the published location ("./PATTERN.md", "../LICENSE"), so they do not
# resolve inside the vault. That is deliberate: the published file stays
# byte-identical to its source instead of being a rewrite of it.
#
# These three are configurable, and each is EMPTY-SAFE: an empty value
# means "not configured" and the check is skipped. A prefix of "" matches
# every path, so every use tests the value before the prefix.
PUBLISH_DIR = os.environ.get("AMC_PUBLISH_DIR", "")

# A dated import snapshot — extracts kept for reference, not live documents.
# CONVENTIONS.md §2.4 records it as a known exception, so its files are not
# held to the live-document frontmatter rule.
SNAPSHOT_DIR = os.environ.get("AMC_SNAPSHOT_DIR", "")

# The AMC's own documents: design, ops and publish notes.
AMC_DIR = os.environ.get("AMC_DIR", "")


# ----------------------------------------------------------------------
def blank_noise(text):
    """Blank out fenced code blocks and inline code, preserving line count,
    so line numbers stay correct and example links are not scanned."""
    out = []
    in_fence = False
    for line in text.split("\n"):
        if FENCE_LINE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        out.append(INLINE_CODE.sub(" ", line))
    return "\n".join(out)


def parse_frontmatter(text):
    """Minimal YAML-ish frontmatter parser. Returns (dict, body, body_offset)."""
    if not text.startswith("---"):
        return None, text, 0
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text, 0
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return None, text, 0
    fm = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        else:
            val = val.strip("'\"")
        fm[key.strip()] = val
    return fm, "\n".join(lines[end + 1:]), end + 1


def looks_like_example(slug):
    """True when a wikilink is a template placeholder rather than a real link."""
    if " " in slug or any(c in slug for c in "'\",[]{}"):
        return True
    letters = [c for c in slug if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return True
    if slug.lower().endswith(IMAGE_EXT):
        return True
    return False


def pending_slugs():
    """Slugs the wiki index declares as 'referenced but not yet created'."""
    out = set()
    p = os.path.join(VAULT, "wiki", "index.md")
    if not os.path.isfile(p):
        return out
    text = open(p, encoding="utf-8", errors="replace").read()
    if "## Pages referenced but not yet created" not in text:
        return out
    section = text.split("## Pages referenced but not yet created", 1)[1]
    for m in WIKI_LINK.finditer(section):
        out.add(os.path.splitext(os.path.basename(m.group(1).strip()))[0])
    return out


def pending_sections(text):
    """Line numbers that sit under a heading declaring something pending."""
    out = set()
    lines = text.split("\n")
    pending = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            pending = bool(PENDING_HEADING.search(line))
            continue
        if pending:
            out.add(i)
    return out


def git_uncommitted():
    try:
        # Never take the index lock. Git refreshes and rewrites the index as
        # part of `status`, and in a restricted agent workspace it cannot
        # remove the lock file it creates — the leftover then blocks every
        # later git write, including the human's. GIT_OPTIONAL_LOCKS=0 makes
        # the optional refresh read-only, which is what a linter should be.
        env = dict(os.environ)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        r = subprocess.run(["git", "status", "--porcelain"], cwd=VAULT,
                           capture_output=True, text=True, timeout=90, env=env)
        if r.returncode != 0:
            return None
        return [l for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        return None


# ----------------------------------------------------------------------
def main():
    global VAULT
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--quiet", action="store_true", help="errors only")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--vault", default=VAULT)
    args = ap.parse_args()

    # realpath, not abspath: the vault root is a symlink into iCloud Drive.
    # os.walk then yields physical paths, and every path we build from them
    # stays comparable with VAULT. Without this, relative links resolve
    # against the physical CWD while VAULT still holds the symlink path, the
    # inbound map gets keys that match nothing, and every markdown-linked page
    # is wrongly reported as an orphan.
    VAULT = os.path.realpath(os.path.abspath(os.path.expanduser(args.vault)))
    os.chdir(VAULT)

    errors, warnings, info = [], [], []

    stems = defaultdict(list)
    md_files = []
    for dp, dn, fn in os.walk(VAULT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for n in fn:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, VAULT)
            stems[os.path.splitext(n)[0]].append(rel)
            if n.endswith(".md"):
                md_files.append((p, rel))

    index_pending = pending_slugs()
    inbound = defaultdict(set)
    page_fm = {}

    for p, rel in md_files:
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fm, body, offset = parse_frontmatter(raw)
        page_fm[rel] = fm
        # Absolute, so a relative link resolves against the page's own
        # directory rather than against the current working directory.
        base_dir = os.path.dirname(p)

        # --- frontmatter ---
        if fm is None:
            if rel.startswith("wiki/"):
                errors.append(("missing-frontmatter", rel, 1,
                               "wiki page has no frontmatter (wiki/schema.md requires it)"))
            elif SNAPSHOT_DIR and rel.startswith(SNAPSHOT_DIR):
                # A dated import snapshot, not an AMC class. CONVENTIONS.md
                # §2.4: "Its files are extracts, not live documents. Read them
                # for reference; do not treat them as current, and do not add
                # to them." Adding frontmatter to them would be adding to them.
                pass
            elif AMC_DIR and rel.startswith(AMC_DIR):
                warnings.append(("missing-frontmatter", rel, 1,
                                 "AMC document has no frontmatter"))
        else:
            ftype = fm.get("type", "")
            if ftype and ftype not in VAULT_TYPES:
                warnings.append(("unknown-type", rel, 1,
                                 f"type '{ftype}' is not in the known vocabulary"))
            fstatus = (fm.get("status") or "").strip()
            if fstatus and fstatus.lower() not in VAULT_STATUSES:
                warnings.append(("unknown-status", rel, 1,
                                 f"status '{fstatus}' is not a known lifecycle state"))
            # The category axis. A note that carries a `type:` should carry a
            # `category:` too, and the category must be one of the nine.
            # Without this the axis drifts the way `type:` did.
            if ftype and not rel.startswith("Categories/"):
                cat = (fm.get("category") or "").strip()
                if not cat:
                    warnings.append(("missing-category", rel, 1,
                                     "note has a type but no category"))
                elif cat not in VAULT_CATEGORIES:
                    warnings.append(("unknown-category", rel, 1,
                                     f"category '{cat}' is not in the known vocabulary"))
            if rel.startswith("wiki/") and ftype in WIKI_REQUIRED:
                for req in WIKI_REQUIRED[ftype]:
                    if req not in fm:
                        errors.append(("missing-frontmatter-field", rel, 1,
                                       f"wiki {ftype} page is missing '{req}'"))
            if fm.get("status", "").lower() == "stale":
                info.append(("stale", rel, 1,
                             "flagged status: stale — in the pruning queue"))
            if ftype == "moved-pointer":
                target = fm.get("moved_to", "")
                if target and not os.path.exists(os.path.join(VAULT, target)):
                    errors.append(("broken-move-pointer", rel, 1,
                                   f"moved_to '{target}' does not exist"))
                else:
                    info.append(("pending-stub", rel, 1,
                                 f"pointer stub — target {target} exists"))

        # --- links ---
        scanned = blank_noise(body)
        pend_lines = pending_sections(body)
        is_doc = rel in DOC_FILES or bool(PUBLISH_DIR and rel.startswith(PUBLISH_DIR))
        for i, line in enumerate(scanned.split("\n"), 1):
            lineno = i + offset
            for t in MD_LINK.findall(line):
                clean = unquote(t.split("#")[0])
                if not clean:
                    continue
                if clean.startswith(("http://", "https://", "mailto:", "obsidian://", "data:")):
                    continue
                if clean.startswith("#"):
                    continue
                resolved = os.path.normpath(os.path.join(base_dir, clean.rstrip("/")))
                if os.path.exists(resolved):
                    inbound[os.path.relpath(resolved, VAULT)].add(rel)
                else:
                    (info if is_doc else errors).append(
                        ("dangling-md-link", rel, lineno,
                         f"[{t}] -> {os.path.relpath(os.path.abspath(resolved), VAULT)}"))
            for m in WIKI_LINK.finditer(line):
                slug = os.path.splitext(os.path.basename(m.group(1).strip()))[0]
                if slug in stems:
                    for f in stems[slug]:
                        inbound[f].add(rel)
                elif looks_like_example(slug):
                    info.append(("example-wikilink", rel, lineno,
                                 f"[[{slug}]] reads as a template example, not a link"))
                elif slug in index_pending:
                    info.append(("pending-wikilink", rel, lineno,
                                 f"[[{slug}]] is declared not-yet-created in wiki/index.md"))
                elif i in pend_lines:
                    info.append(("pending-wikilink", rel, lineno,
                                 f"[[{slug}]] is declared pending in this page"))
                elif is_doc:
                    info.append(("example-wikilink", rel, lineno,
                                 f"[[{slug}]] in a conventions file, treated as an example"))
                else:
                    errors.append(("dangling-wikilink", rel, lineno,
                                   f"[[{slug}]] has no matching file"))

    # --- orphans ---
    for p, rel in md_files:
        if rel in ("README.md", "AGENTS.md", "hot.md"):
            continue
        if inbound.get(rel):
            continue
        fm = page_fm.get(rel)
        if not fm or not fm.get("type"):
            continue
        if fm.get("type") == "moved-pointer":
            continue
        if rel.startswith("wiki/"):
            errors.append(("orphan", rel, 1,
                           "nothing links to this wiki page (wiki/schema.md forbids orphans)"))
        else:
            info.append(("orphan", rel, 1, "nothing links to this page"))

    uncommitted = git_uncommitted()
    if uncommitted:
        info.append(("uncommitted", ".", 0,
                     f"{len(uncommitted)} uncommitted change(s) in git"))

    result = {
        "errors": [{"kind": k, "file": f, "line": n, "detail": d} for k, f, n, d in errors],
        "warnings": [{"kind": k, "file": f, "line": n, "detail": d} for k, f, n, d in warnings],
        "info": [{"kind": k, "file": f, "line": n, "detail": d} for k, f, n, d in info],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"memory-lint — {VAULT}")
        print(f"scanned {len(md_files)} markdown files")
        print()

        def show(title, items, show_info=True):
            if not items:
                return
            if title == "INFO" and not show_info:
                return
            print(f"--- {title} ({len(items)}) " + "-" * max(0, 46 - len(title)))
            for kind, f, line, detail in items:
                loc = f"{f}:{line}" if line else f
                print(f"  [{kind}] {loc}  {detail}")
            print()

        show("ERRORS", errors)
        show("WARNINGS", warnings)
        show("INFO", info, show_info=not args.quiet)

        n_err = len(errors) + (len(warnings) if args.strict else 0)
        print("=" * 62)
        if n_err:
            print(f"FAILED — {len(errors)} error(s)"
                  + (f", {len(warnings)} warning(s) (strict mode)" if args.strict else ""))
        else:
            print(f"PASSED — {len(errors)} errors, {len(warnings)} warnings")
        print("=" * 62)

    return 1 if (errors or (args.strict and warnings)) else 0


if __name__ == "__main__":
    sys.exit(main())
