# Categories

The index of the closed category set. Every category is a note, so Bases views can filter on it.

**What belongs here.** Nothing. This note is the index of the others.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[categories]]"
category: categories
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("categories"))'
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
