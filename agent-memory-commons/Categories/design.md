# Design

Why the system is the way it is. Architecture, patterns, rationale, and the decisions behind them.

**What belongs here.** Architecture documents, pattern write-ups, recorded decisions, measurements that changed a design.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[design]]"
category: design
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("design"))'
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
