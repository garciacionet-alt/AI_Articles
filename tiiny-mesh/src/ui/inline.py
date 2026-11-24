#!/usr/bin/env python3
"""Inline the dashboard sources into ui/index.html.

The gateway answers GET /ui by serving index.html, so the page has to carry
its own CSS and JS - otherwise the browser would ask for /mesh-dashboard.js
and the gateway would have to grow a static-file route.

Edit the two source files, then run:

    python3 ui/inline.py

It rewrites index.html in place, between the generated markers. Safe to run
repeatedly.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

BLOCKS = [
    ("MESH_CSS", os.path.join(HERE, "mesh-dashboard.css")),
    ("MESH_JS", os.path.join(HERE, "mesh-dashboard.js")),
]


def main() -> int:
    with open(INDEX, "r", encoding="utf-8") as fh:
        html = fh.read()

    for name, path in BLOCKS:
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read().rstrip("\n")
        if "</script" in body.lower():
            print("%s: refusing to inline - contains a </script> sequence" % name)
            return 1
        start = "/* == %s (generated from %s) == */" % (name, os.path.basename(path))
        end = "/* == end %s == */" % name
        i = html.find(start)
        j = html.find(end)
        if i == -1 or j == -1 or j < i:
            print("%s: markers not found in index.html" % name)
            return 1
        head = html[: i + len(start)]
        tail = html[j:]
        html = head + "\n" + body + "\n" + tail
        print("inlined %s (%d bytes)" % (os.path.basename(path), len(body)))

    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("wrote %s (%d bytes)" % (INDEX, len(html)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
