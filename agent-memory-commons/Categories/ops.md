# Operations

What to do. Procedures, conventions, catalogs, and the rules an agent follows when it works in the vault.

**What belongs here.** Procedures, the vault catalog, session-end protocol, cron ownership rules, the lint.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[ops]]"
category: ops
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("ops"))'
properties:
  note.type:
    displayName: "Type"
  note.status:
    displayName: "Status"
views:
  - type: table
    name: "Notes in this category"
    order:
      - file.name
      - type
      - status
      - file.folder
```

## Related
