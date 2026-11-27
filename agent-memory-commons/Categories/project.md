# Project

One unit of work. A job search, an appliance conversion, an agent build — anything with its own deliverable.

**What belongs here.** Project folders, their plans, their status, their deliverables.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[project]]"
category: project
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("project"))'
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
