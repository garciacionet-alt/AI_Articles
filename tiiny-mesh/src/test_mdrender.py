#!/usr/bin/env python3
"""Markdown renderer tests — offline."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdrender

def t(name, fn):
    try:
        fn()
        print("  ok   ", name)
        return 0
    except AssertionError as e:
        print("  FAIL ", name, "-", e)
        return 1

fails = 0

def test_constructs():
    sample = """# Header 1
## Header 2

This is a paragraph with **bold text** and `inline code` and a [link](https://example.com).

---

- Bullet item 1
- Bullet item 2

1. Ordered item 1
2. Ordered item 2

| Col A | Col B |
|---|---|
| Val 1 | Val 2 |

```bash
echo "hello world"
```
"""
    html = mdrender.render_markdown(sample)
    assert "<h1>Header 1</h1>" in html, html
    assert "<h2>Header 2</h2>" in html, html
    assert "<strong>bold text</strong>" in html, html
    assert "<code>inline code</code>" in html, html
    assert '<a href="https://example.com"' in html, html
    assert "<hr>" in html, html
    assert "<ul>" in html and "<li>Bullet item 1</li>" in html, html
    assert "<ol>" in html and "<li>Ordered item 1</li>" in html, html
    assert "<table>" in html and "<th>Col A</th>" in html and "<td>Val 1</td>" in html, html
    assert '<pre><code class="language-bash">' in html, html
    assert 'echo &quot;hello world&quot;' in html or 'echo "hello world"' in html, html

def test_xss_prevention():
    malicious = "<script>alert('xss')</script>"
    html = mdrender.render_markdown(malicious)
    assert "<script>" not in html, "Raw script tag found in HTML!"
    assert "&lt;script&gt;" in html, "Escaped script tag missing!"

fails += t("all markdown constructs render correctly", test_constructs)
fails += t("xss injection prevented via HTML escaping", test_xss_prevention)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
