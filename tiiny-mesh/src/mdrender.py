#!/usr/bin/env python3
"""Minimal, dependency-free Markdown to HTML renderer for TiinyMesh.

Standard library only. Escapes all raw HTML for safe rendering.
Supports headings, paragraphs, lists, tables, fenced code blocks, bold,
inline code, links, and horizontal rules.
"""

from __future__ import annotations

import re


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _format_inline(text: str) -> str:
    # First escape HTML
    s = _escape(text)

    # Inline code: `code`
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    # Bold: **bold**
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    # Links: [label](url)
    def _link_sub(m):
        label, url = m.group(1), m.group(2)
        # Only allow safe http, https, relative or anchor URLs
        if url.startswith(("http://", "https://", "/", "#", "./", "../")):
            return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
        return f'<a href="#">{label}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_sub, s)
    return s


def render_markdown(md: str, title: str = "TiinyMesh README") -> str:
    lines = md.splitlines()
    html_parts: list[str] = []

    in_code = False
    code_lang = ""
    code_lines: list[str] = []

    in_table = False
    table_headers: list[str] = []
    table_rows: list[list[str]] = []

    in_list: str | None = None  # "ul" or "ol"

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append(f"</{in_list}>")
            in_list = None

    def close_table():
        nonlocal in_table, table_headers, table_rows
        if in_table:
            out = ['<div class="table-wrap"><table><thead><tr>']
            for h in table_headers:
                out.append(f"<th>{_format_inline(h)}</th>")
            out.append("</tr></thead><tbody>")
            for row in table_rows:
                out.append("<tr>")
                for cell in row:
                    out.append(f"<td>{_format_inline(cell)}</td>")
                out.append("</tr>")
            out.append("</tbody></table></div>")
            html_parts.append("".join(out))
            in_table = False
            table_headers = []
            table_rows = []

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            close_list()
            close_table()
            if in_code:
                # closing code block
                escaped_code = _escape("\n".join(code_lines))
                cls_attr = f' class="language-{_escape(code_lang)}"' if code_lang else ""
                html_parts.append(f"<pre><code{cls_attr}>{escaped_code}</code></pre>")
                in_code = False
                code_lines = []
                code_lang = ""
            else:
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            idx += 1
            continue

        if in_code:
            code_lines.append(line)
            idx += 1
            continue

        # Blank line
        if not stripped:
            close_list()
            close_table()
            idx += 1
            continue

        # Horizontal rule
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", stripped):
            close_list()
            close_table()
            html_parts.append("<hr>")
            idx += 1
            continue

        # Headings (# h1 to ###### h6)
        h_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if h_match:
            close_list()
            close_table()
            level = len(h_match.group(1))
            htext = _format_inline(h_match.group(2))
            html_parts.append(f"<h{level}>{htext}</h{level}>")
            idx += 1
            continue

        # Table detection
        if stripped.startswith("|") and stripped.endswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Check if next line is table separator
            if not in_table:
                if idx + 1 < len(lines):
                    next_stripped = lines[idx + 1].strip()
                    if next_stripped.startswith("|") and re.match(r"^\|(\s*:?-+:?\s*\|)+$", next_stripped):
                        in_table = True
                        table_headers = cells
                        table_rows = []
                        idx += 2
                        continue
            else:
                table_rows.append(cells)
                idx += 1
                continue

        close_table()

        # Bullet list
        ul_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        if ul_match:
            if in_list != "ul":
                close_list()
                html_parts.append("<ul>")
                in_list = "ul"
            html_parts.append(f"<li>{_format_inline(ul_match.group(1))}</li>")
            idx += 1
            continue

        # Ordered list
        ol_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ol_match:
            if in_list != "ol":
                close_list()
                html_parts.append("<ol>")
                in_list = "ol"
            html_parts.append(f"<li>{_format_inline(ol_match.group(1))}</li>")
            idx += 1
            continue

        close_list()

        # Paragraph
        html_parts.append(f"<p>{_format_inline(stripped)}</p>")
        idx += 1

    close_list()
    close_table()

    body = "\n".join(html_parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
  :root {{
    --bg: #0f141c;
    --card: #18202c;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --border: #2e3b4e;
    --code-bg: #111827;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f8fafc;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #0284c7;
      --border: #e2e8f0;
      --code-bg: #f1f5f9;
    }}
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 2rem 1rem;
    line-height: 1.6;
  }}
  .container {{
    max-width: 860px;
    margin: 0 auto;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 2.5rem;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
  }}
  h1, h2, h3, h4 {{ color: var(--text); margin-top: 1.8rem; margin-bottom: 0.8rem; }}
  h1 {{ font-size: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
  h2 {{ font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.3rem; }}
  h3 {{ font-size: 1.15rem; }}
  p, li {{ color: var(--text); }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 0.9em; background: var(--code-bg); padding: 0.2em 0.4em; border-radius: 4px; }}
  pre {{ background: var(--code-bg); padding: 1rem; border-radius: 6px; overflow-x: auto; border: 1px solid var(--border); }}
  pre code {{ background: transparent; padding: 0; }}
  hr {{ border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }}
  .table-wrap {{ overflow-x: auto; margin: 1.5rem 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid var(--border); padding: 0.5rem 0.8rem; text-align: left; }}
  th {{ background: var(--code-bg); font-weight: 600; }}
  ul, ol {{ padding-left: 1.5rem; }}
  li {{ margin-bottom: 0.3rem; }}
</style>
</head>
<body>
<div class="container">
{body}
</div>
</body>
</html>"""
