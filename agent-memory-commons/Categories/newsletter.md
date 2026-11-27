# Newsletter

The newsletter pipeline end to end: the weekly survey, the package, the carousel, and the beehiiv publication.

**What belongs here.** Survey corpora and audits, package specs and builds, the carousel and teaser, monetization notes, archived editions.

**The authority** for a category is the document that governs it — the folder's own README, and the design or ops note that describes it. See Related.

Every note in this category carries this link in its `categories` property:

```yaml
categories:
  - "[[newsletter]]"
category: newsletter
```

## What is in this category

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'categories.contains(link("newsletter"))'
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
