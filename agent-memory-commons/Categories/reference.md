# Reference

About things outside the commons. Models, vendors, people, companies, and material gathered from elsewhere.

**What belongs here.** Vendor and model references, the LLM wiki, clippings and gathered external material.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[reference]]"
category: reference
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("reference"))'
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
