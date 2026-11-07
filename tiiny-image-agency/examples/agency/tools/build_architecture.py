"""Build architecture.html — the architecture diagram.

WHY A GENERATOR
---------------
The diagram was hand-placed SVG: every box had a hand-computed x, y and
a hand-computed y for each of its text lines. It was accurate on 5 Nov
and wrong on 6 Nov, because the system it drew was a third of the
system that exists: no CLI, no judge as a first-class element, no
download path, no research cards, and a NPU pool that had since
changed size.

The failure mode of hand-placed SVG is not that it looks wrong. It
looks FINE. It looks like a finished diagram of a system that no
longer exists, which is worse than no diagram at all.

So the layout is data, and the geometry is computed. A box declares
where it is and what it says; the generator works out the text
positions, and checks that no two boxes overlap. Change the data and
the diagram is right again.

THE DIAGRAM'S CLAIM
-------------------
It is not a pretty picture of the code. It is a picture of the ONE
constraint that decides everything else: a finite NPU pool that every
model shares, where loading a model is a SWAP and not an addition.
Everything in the middle column exists because of that.

    python3 tools/build_architecture.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "architecture.html"

#: The surface serves its own folder, so the diagram has to be IN that
#: folder for the surface's link to work. It is written twice from one
#: source - the generator - because a copy is a thing that drifts.
SURFACE_COPY = PROJECT_ROOT / "app" / "web" / "architecture.html"

#: The palette. Cyan is the surface, emerald the logic, violet the data,
#: amber the device, orange the boundary, rose the constraint.
KIND = {
    "frontend": ("rgba(8,51,68,0.4)", "#22d3ee"),
    "backend": ("rgba(6,78,59,0.4)", "#34d399"),
    "data": ("rgba(76,29,149,0.4)", "#a78bfa"),
    "device": ("rgba(120,53,15,0.3)", "#fbbf24"),
    "adapter": ("rgba(251,146,60,0.3)", "#fb923c"),
    "constraint": ("rgba(136,19,55,0.4)", "#fb7185"),
}

MARKER = {
    "#22d3ee": "ah-cyan", "#34d399": "ah-emerald", "#a78bfa": "ah-violet",
    "#fbbf24": "ah-amber", "#fb923c": "ah-orange", "#fb7185": "ah-rose",
    "#64748b": "ah",
}

#: Text colour by emphasis. "warn" is a caution, "crit" is a hazard,
#: "ok" is a relief, "dim" is a note.
COLOUR = {
    "normal": "#94a3b8",
    "warn": "#fbbf24",
    "crit": "#fb7185",
    "ok": "#34d399",
    "dim": "#64748b",
}


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def box(x, y, w, h, kind, title, lines, title_size=11, title_colour="white"):
    """One box: a rectangle, a title, and its lines.

    A line is (text, emphasis) or just text for the plain kind. The
    first line of an accent group is separated from the body, because
    a caution should not sit flush against a list of facts.
    """
    fill, stroke = KIND[kind]
    out = [
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
        f'  <text x="{x + w // 2}" y="{y + 20}" fill="{title_colour}" '
        f'font-size="{title_size}" font-weight="600" text-anchor="middle">'
        f'{esc(title)}</text>',
    ]
    body_y = y + 36
    for line in lines:
        if isinstance(line, tuple):
            text, emphasis = line
        else:
            text, emphasis = line, "normal"
        out.append(
            f'  <text x="{x + w // 2}" y="{body_y}" fill="{COLOUR[emphasis]}" '
            f'font-size="8" text-anchor="middle">{esc(text)}</text>')
        body_y += 12
    return "\n".join(out)


def box_height(title_size, lines):
    """The height a box needs for its text."""
    height = 30 + 12 * len(lines)
    return height + 8


def arrow(x1, y1, x2, y2, colour="#64748b", dashed=False, label=None,
          label_x=None, label_y=None, anchor="middle"):
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    out = [f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
           f'stroke="{colour}" stroke-width="1.5"{dash} '
           f'marker-end="url(#{MARKER[colour]})"/>']
    if label:
        lx = label_x if label_x is not None else (x1 + x2) // 2
        ly = label_y if label_y is not None else (y1 + y2) // 2 - 5
        out.append(f'  <text x="{lx}" y="{ly}" fill="{COLOUR["normal"]}" '
                   f'font-size="8" text-anchor="{anchor}">{esc(label)}</text>')
    return "\n".join(out)


def path(d, colour="#64748b", dashed=False, label=None, label_x=None,
         label_y=None, anchor="middle"):
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    out = [f'  <path d="{d}" fill="none" stroke="{colour}" '
           f'stroke-width="1.5"{dash} marker-end="url(#{MARKER[colour]})"/>']
    if label:
        out.append(f'  <text x="{label_x}" y="{label_y}" '
                   f'fill="{COLOUR["normal"]}" font-size="8" '
                   f'text-anchor="{anchor}">{esc(label)}</text>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The layout, as data.
# ---------------------------------------------------------------------------

# Each entry: (key, x, y, w, kind, title, lines, title_size, title_colour)
BOXES = [
    # -- actors -----------------------------------------------------------
    ("developer", 25, 125, 105, "frontend", "Developer",
     ["browser", "or a script"], 11, "white"),
    ("agent", 25, 640, 105, "frontend", "Agent",
     ["via the skill"], 11, "white"),

    # -- the clients of the API ------------------------------------------
    ("surface", 205, 105, 170, "frontend", "Work Surface",
     ["• conversation pane", "• canvas + alpha grid", "• model badge",
      "• NPU meter", ("swap banner", "warn"), ("iteration strip", "warn")],
     11, "white"),
    ("api", 205, 250, 170, "frontend", "Public API",
     ["/v1/plan · /v1/generate", "/v1/iterate · /v1/npu",
      "/v1/models · /v1/models/card", "/v1/session/…/events",
      ("no bypass to the device", "crit")], 11, "white"),
    ("cli", 205, 375, 170, "frontend", "CLI — `tis`",
     ["plan · generate · iterate", "alpha · npu · models",
      ("an HTTP client of the API", "ok")], 11, "white"),
    ("assets", 205, 480, 170, "data", "Asset Store",
     ["PNG · alpha kept", "prompt lineage", "requirements + critique",
      ("every asset reproducible", "ok")], 11, "white"),

    # -- the logic --------------------------------------------------------
    ("orchestrator", 425, 105, 225, "backend", "Orchestrator",
     ["planner → requirement vector", "resolver → model + justification",
      "dialect translator → prompt", "critic → image vs vector",
      ("the LLM proposes;", "ok"), ("the resolver disposes", "ok"),
      ("retry bound: 3 per turn", "crit")], 12, "white"),
    ("registry", 425, 285, 225, "data", "Model Registry",
     ["device facts (live) + overlay (curated)", "research cards: measured",
      "14 image models · dialect · NPU cost",
      ("device desc metadata is not trusted", "crit")], 11, "white"),
    ("critic", 425, 395, 225, "backend", "Critic",
     [("judges the PROMPT or the PIXELS", "ok"),
      ("a vision judge is a chosen model", "ok"),
      ("a change is an instruction", "warn"),
      ("a dimension request is dropped", "warn")], 11, "white"),

    ("residency", 670, 105, 225, "device", "Residency Manager",
     ["NPU budget check", "swap → hold, evict, load",
      "restore after generation", "download if not on disk",
      ("hold file written BEFORE load", "warn"),
      ("watchdog would evict a swap", "crit")], 11, "white"),
    ("adapter", 670, 265, 225, "adapter", "Device Adapter",
     ["typed client — the only place", "that reads the bearer",
      ("over the LAN, to the device", "warn")], 11, "white"),

    # -- the right-hand column --------------------------------------------
    ("constraint", 915, 105, 235, "constraint", "THE CONSTRAINT",
     [], 10, "#fb7185"),
    ("download", 915, 340, 235, "device", "THE DOWNLOAD PATH",
     ["a model that is not on disk", "is fetched before the generation",
      "10.6 GiB · about five minutes",
      ("278 GiB free — storage is fine", "ok"),
      ("the NPU pool is the constraint", "warn")], 10, "#fbbf24"),
    ("events", 915, 480, 235, "backend", "THE EVENT STREAM",
     ["the bus REPLAYS to late", "subscribers, so the replay",
      "carries earlier jobs' events",
      ("filter by job_id, always", "crit")], 10, "#34d399"),
    ("legend", 915, 615, 235, "frontend", "Legend", [], 10, "white"),

    # -- the coordination that makes the device shareable -----------------
    #
    # This is the piece that is invisible from inside one agent, and it
    # is where every problem in this project has lived: the lock says
    # who owns the device, the hold says what must stay resident, and
    # the notice in hot.md is what tells the OTHER agents either fact.
    ("coordination", 205, 580, 700, "device",
     "Cross-agent coordination — one device, one lock",
     ["lock  ~/.hermes/tiiny-lock.json   who owns the device right now",
      "hold  ~/.hermes/tiiny-hold   what must stay resident",
      "notice  hot.md   the AMC's board — every other agent reads it",
      ("a lock that announces nothing is a lock nobody respects", "warn")],
     11, "white"),

    # -- the device --------------------------------------------------------
    ("pool", 400, 820, 230, "constraint", "NPU POOL",
     ["47.9 GiB · one shared pool", "finite · loading evicts",
      ("a model is a SWAP", "crit"),
      ("39.9 / 47.9 GiB at baseline", "warn"),
      ("86% utilised · the CLI is truth", "warn")], 11, "white"),
    ("openai", 655, 820, 240, "backend", "OpenAI-compat",
     ["/v1/chat/completions", "/v1/images/generations", "/v1/models",
      ("resident models only", "ok"), ("404 = not resident", "crit")],
     11, "white"),
    ("management", 920, 820, 225, "device", "Management",
     ["/api/v1/models/online", "/api/v1/sys/status",
      "npu_usage · load · evict", ("tiiny load needs a TTY", "crit"),
      ("absent from openapi.json", "dim")], 11, "white"),
]

LEGEND = [
    ("frontend", "Frontend / surface"),
    ("backend", "Backend / logic"),
    ("data", "Data / registry"),
    ("device", "Device / management"),
    ("adapter", "Adapter / boundary"),
    ("constraint", "Constraint / secret"),
]


def build_svg() -> str:
    by_key = {entry[0]: entry for entry in BOXES}
    out = ['  <svg viewBox="0 0 1180 1010" role="img" '
           'aria-label="Tiiny Image Agency architecture">']
    out.append("""    <defs>
      <marker id="ah" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />
      </marker>
      <marker id="ah-cyan" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#22d3ee" />
      </marker>
      <marker id="ah-emerald" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#34d399" />
      </marker>
      <marker id="ah-violet" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#a78bfa" />
      </marker>
      <marker id="ah-amber" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#fbbf24" />
      </marker>
      <marker id="ah-orange" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#fb923c" />
      </marker>
      <marker id="ah-rose" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
        <polygon points="0 0, 10 3.5, 0 7" fill="#fb7185" />
      </marker>
      <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
        <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="0.5"/>
      </pattern>
    </defs>

    <rect width="100%" height="100%" fill="url(#grid)" />""")

    # Boundaries.
    out.append('    <rect x="185" y="60" width="965" height="680" rx="12" '
               'fill="rgba(34,211,238,0.04)" stroke="#22d3ee" stroke-width="1" '
               'stroke-dasharray="8,4"/>')
    out.append('    <text x="199" y="80" fill="#22d3ee" font-size="10" '
               'font-weight="600">Tiiny Image Agency — runs on the Mac, not '
               'the device</text>')
    out.append('    <rect x="380" y="790" width="790" height="195" rx="12" '
               'fill="rgba(251,191,36,0.05)" stroke="#fbbf24" stroke-width="1" '
               'stroke-dasharray="8,4"/>')
    out.append('    <text x="394" y="810" fill="#fbbf24" font-size="10" '
               'font-weight="600">Tiiny Pocket Lab · LAN</text>')

    # -- arrows, drawn before the boxes they connect ----------------------
    out.append(arrow(130, 150, 203, 150, "#22d3ee", label="HTTPS / SSE",
                     label_x=166, label_y=143))
    out.append(path("M 77 183 L 77 415 L 203 415", "#22d3ee",
                    label="shell", label_x=140, label_y=408))
    out.append(path("M 130 669 L 172 669 L 172 297 L 203 297", "#22d3ee",
                    label="skill → REST", label_x=150, label_y=262,
                    anchor="end"))
    out.append(arrow(290, 373, 290, 347, "#22d3ee", label="HTTP client",
                     label_x=320, label_y=365))
    out.append(path("M 375 297 L 400 297 L 400 180 L 423 180", "#34d399",
                    label="HTTPS", label_x=399, label_y=172))
    out.append(arrow(537, 260, 537, 283, "#a78bfa", label="query",
                     label_x=548, label_y=270))
    out.append(arrow(610, 283, 610, 260, "#a78bfa"))
    out.append(path("M 440 260 L 415 260 L 415 190 L 423 190", "#fbbf24",
                    label="load plan", label_x=408, label_y=230, anchor="end"))
    out.append(path("M 650 425 L 662 425 L 662 190 L 668 190", "#fb7185",
                    dashed=True))
    out.append(arrow(650, 190, 668, 190, "#fbbf24"))
    out.append(path("M 400 297 L 395 297 L 395 560 L 373 560", "#a78bfa",
                    label="lineage", label_x=390, label_y=430, anchor="end"))
    # The adapter reaches the device down the GAP between the middle
    # column and the right one, so the line does not pass through the
    # coordination box. A line through a box is a line that says
    # something untrue.
    out.append(path("M 895 300 L 908 300 L 908 890 L 897 890", "#64748b"))
    out.append(arrow(630, 890, 653, 890, "#64748b"))
    out.append(arrow(895, 890, 918, 890, "#64748b"))
    # The residency manager WRITES the lock and the hold; the board
    # tells everyone else. That is the whole sharing mechanism. The
    # label sits in the empty band above the coordination box, because
    # the gap between the two columns is too narrow to write in.
    out.append(path("M 655 580 L 655 300 L 668 300", "#fbbf24", dashed=True,
                    label="writes the lock", label_x=652, label_y=562,
                    anchor="end"))
    # The store is where a missing model comes from. The line runs up the
    # RIGHT edge, clear of the event-stream box, because a line through
    # a box is a line that says something untrue.
    out.append(path("M 1125 860 L 1162 860 L 1162 402 L 1152 402", "#fbbf24",
                    dashed=True, label="the store is the source", label_x=1125,
                    label_y=800, anchor="end"))

    # -- the boxes ---------------------------------------------------------
    for key, x, y, w, kind, title, lines, tsize, tcolour in BOXES:
        if key in ("constraint", "legend"):
            # These two are drawn by hand below: the constraint is not a
            # list of lines, and the legend is a swatch list.
            continue
        out.append(box(x, y, w, box_height(tsize, lines), kind, title, lines,
                       tsize, tcolour))

    # -- the constraint box, which is not a list ---------------------------
    cx, cy, cw = 915, 105, 235
    out.append(f'  <rect x="{cx}" y="{cy}" width="{cw}" height="220" rx="8" '
               'fill="rgba(136,19,55,0.25)" stroke="#fb7185" stroke-width="1.5"/>')
    out.append(f'  <text x="{cx + cw // 2}" y="{cy + 20}" fill="#fb7185" '
               'font-size="10" font-weight="600" text-anchor="middle">'
               'THE CONSTRAINT</text>')
    for text, colour, ty, anchor in [
        ("planner · Qwen3-Coder-30B-A3B", "#fb7185", 44, "start"),
        ("55%", "#fb7185", 44, "end"),
        ("Qwen-Image-2.1 — only native RGBA", "#fb7185", 62, "start"),
        ("62%", "#fb7185", 62, "end"),
    ]:
        lx = cx + 12 if anchor == "start" else cx + cw - 12
        out.append(f'  <text x="{lx}" y="{cy + ty}" fill="{colour}" '
                   f'font-size="8" text-anchor="{anchor}">{esc(text)}</text>')
    out.append(f'  <line x1="{cx + 12}" y1="{cy + 74}" x2="{cx + cw - 12}" '
               f'y2="{cy + 74}" stroke="#fb7185" stroke-width="1" '
               'stroke-dasharray="3,3"/>')
    for text, colour, ty in [
        ("117% — cannot coexist", "white", 92),
        ("The flagship capability is the one", "#94a3b8", 114),
        ("model that evicts the conversation.", "#94a3b8", 126),
        ("12 of 14 models DO coexist.", "#34d399", 150),
        ("The hot path is 78%. 85% FAILS", "#fbbf24", 172),
        ("with 150004 — admitted, then", "#fbbf24", 184),
        ("refused. Admission is not proof.", "#fbbf24", 196),
    ]:
        out.append(f'  <text x="{cx + 12}" y="{cy + ty}" fill="{colour}" '
                   f'font-size="8" text-anchor="start">{esc(text)}</text>')

    # -- the legend --------------------------------------------------------
    lx, ly = 915, 615
    out.append(f'  <rect x="{lx}" y="{ly - 16}" width="235" height="138" rx="6" '
               'fill="rgba(8,51,68,0.4)" stroke="#22d3ee" stroke-width="1.5"/>')
    out.append(f'  <text x="{lx + 12}" y="{ly}" fill="white" font-size="10" '
               'font-weight="600">Legend</text>')
    for index, (kind, label) in enumerate(LEGEND):
        fill, stroke = KIND[kind]
        yy = ly + 14 + index * 15
        out.append(f'  <rect x="{lx + 12}" y="{yy}" width="16" height="10" rx="2" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        out.append(f'  <text x="{lx + 34}" y="{yy + 8}" fill="#94a3b8" '
                   f'font-size="8">{esc(label)}</text>')
    yy = ly + 14 + len(LEGEND) * 15
    out.append(f'  <line x1="{lx + 12}" y1="{yy + 4}" x2="{lx + 28}" '
               f'y2="{yy + 4}" stroke="#fb7185" stroke-width="1" '
               'stroke-dasharray="3,3"/>')
    out.append(f'  <text x="{lx + 34}" y="{yy + 7}" fill="#94a3b8" '
               'font-size="8">Held swap / critical</text>')

    out.append("  </svg>")
    return "\n".join(out)


CSS = """    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'JetBrains Mono', monospace;
      background: #020617;
      min-height: 100vh;
      padding: 2rem;
      color: white;
    }
    .container { max-width: 1240px; margin: 0 auto; }
    .header { margin-bottom: 2rem; }
    .header-row { display: flex; align-items: center; gap: 1rem; margin-bottom: 0.5rem; }
    .pulse-dot {
      width: 12px; height: 12px; background: #22d3ee; border-radius: 50%;
      animation: pulse 2s infinite;
    }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
    h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.025em; }
    .subtitle { color: #94a3b8; font-size: 0.875rem; margin-left: 1.75rem; }
    .diagram-container {
      background: rgba(15, 23, 42, 0.5);
      border-radius: 1rem; border: 1px solid #1e293b; padding: 1.5rem; overflow-x: auto;
    }
    svg { width: 100%; min-width: 1000px; display: block; }
    .cards {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1rem; margin-top: 2rem;
    }
    .card {
      background: rgba(15, 23, 42, 0.5); border-radius: 0.75rem;
      border: 1px solid #1e293b; padding: 1.25rem;
    }
    .card-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
    .card-dot { width: 8px; height: 8px; border-radius: 50%; }
    .card-dot.cyan { background: #22d3ee; }
    .card-dot.emerald { background: #34d399; }
    .card-dot.violet { background: #a78bfa; }
    .card-dot.amber { background: #fbbf24; }
    .card-dot.rose { background: #fb7185; }
    .card-dot.orange { background: #fb923c; }
    .card h3 { font-size: 0.875rem; font-weight: 600; }
    .card ul { list-style: none; color: #94a3b8; font-size: 0.75rem; }
    .card li { margin-bottom: 0.375rem; }
    .card strong { color: #e2e8f0; }
    .card code { color: #22d3ee; }
    .footer { text-align: center; margin-top: 1.5rem; color: #475569; font-size: 0.75rem; }
    .warn { color: #fbbf24; }
    .crit { color: #fb7185; }
    .ok { color: #34d399; }"""

CARDS = [
    ("emerald", "The loop", [
        "• Planner → <strong>requirement vector</strong>, never a model name",
        "• Resolver → deterministic model pick + a paragraph explaining it",
        "• Dialect translator rewrites intent for the target model",
        "• Critic judges the <strong>prompt</strong> — or the <strong>pixels</strong>, "
        "if the user picks a model that can see",
        "• Retry bound: 3 generations per user turn",
    ]),
    ("amber", "Residency arithmetic", [
        "• NPU pool: <strong>47.9 GiB</strong>, one shared pool, evicting",
        "• The hot path is planner (55%) + image model (23%) = <span class=\"warn\">78%</span>",
        "• <span class=\"warn\">85% is admitted and then refused</span> — 150004",
        "• <span class=\"warn\">Qwen-Image-2.1 at 62% + planner at 55% = 117%</span> — swap",
        "• The flagship runs alone: the planner is released and restored",
        "• Percentages are the device's claim — measure before trusting",
    ]),
    ("rose", "Four traps, all closed", [
        "• <strong>TTY:</strong> <code>tiiny load</code> needs a pty — <code>script -q /dev/null</code>",
        "• <strong>Watchdog:</strong> re-loads its set every 5 min — the hold is written <em>before</em> the load",
        "• <strong>Replay:</strong> the event bus replays to late subscribers, so every consumer filters by <code>job_id</code>",
        "• <strong>Dimensions:</strong> a judge's change is an instruction — a request for the size is dropped",
        "• The bearer is device-admin grade — the adapter only, never in a response or a log",
    ]),
    ("violet", "Why the registry is three layers", [
        "• <strong>Device facts</strong> — read live from <code>/api/v1/models/online_models</code>; they move",
        "• <strong>Specialty overlay</strong> — hand-curated: what each model is good at, which dialect it wants",
        "• <strong>Research cards</strong> — measured on the appliance by probing it, because the device's own <code>desc</code> is <span class=\"crit\">wrong</span> for at least one model",
        "• A model that is listed is not a model that is downloaded — the resolver will not pick one that is not on disk",
    ]),
    ("violet", "Two roles, two catalogues", [
        "• The <strong>image registry</strong> holds the generators. The <strong>roles catalogue</strong> holds the models that talk and judge",
        "• The talker writes the requirement vector; the judge decides whether the result is good",
        "• <code>vision: true</code> is the flag that matters — a judge that can see judges the <strong>pixels</strong>",
        "• The guide says which models can see, what each costs, and whether the choice <strong>fits</strong> the pool",
        "• 26 conversational models; 16 of them can see an image",
    ]),
    ("cyan", "One rule", [
        "• Agents do not bypass the orchestrator",
        "• A direct call to <code>/v1/images/generations</code> evicts the chat model and the caller will not know what it displaced",
        "• The API exists so that never happens",
        "• The CLI and the skill are HTTP clients of the API, so neither can hold the appliance",
    ]),
    ("orange", "The two surfaces", [
        "• <strong>CLI</strong> — an HTTP client of the API. It holds no credential and cannot reach the device",
        "• <strong>Work surface</strong> — three static files, no build step, served from the API's own port",
        "• <strong>The skill</strong> — the procedure an agent follows, and it names the CLI commands",
        "• The surface shows the model badge, the NPU meter and the swap banner, because the constraint should be visible",
    ]),
]


def build_cards() -> str:
    out = ['    <div class="cards">']
    for dot, title, items in CARDS:
        out.append("      <div class=\"card\">")
        out.append("        <div class=\"card-header\">")
        out.append(f'          <div class="card-dot {dot}"></div>')
        out.append(f"          <h3>{esc(title)}</h3>")
        out.append("        </div>")
        out.append("        <ul>")
        for item in items:
            out.append(f"          <li>{item}</li>")
        out.append("        </ul>")
        out.append("      </div>")
    out.append("    </div>")
    return "\n".join(out)


def check_overlaps() -> int:
    """No two boxes may overlap. A diagram with overlapping boxes is a
    diagram that says two things are true of the same space."""
    boxes = []
    for key, x, y, w, kind, title, lines, tsize, tcolour in BOXES:
        if key in ("constraint", "legend"):
            # Drawn by hand, with their own measured extents.
            continue
        boxes.append((key, x, y, w, box_height(tsize, lines)))
    boxes.append(("constraint", 915, 105, 235, 220))
    boxes.append(("legend", 915, 599, 235, 138))
    problems = 0
    for i, (ka, ax, ay, aw, ah) in enumerate(boxes):
        for kb, bx, by, bw, bh in boxes[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                print(f"  OVERLAP: {ka} and {kb}")
                problems += 1
    return problems


def main() -> int:
    problems = check_overlaps()
    if problems:
        print(f"FAIL: {problems} overlapping box pair(s).", file=sys.stderr)
        return 1

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Tiiny Image Agency Architecture</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
{CSS}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-row">
        <div class="pulse-dot"></div>
        <h1>Tiiny Image Agency — Architecture</h1>
      </div>
      <p class="subtitle">Plan → resolve → load → generate → critique, with an NPU residency manager in the middle. Facts read from the device 2026-11-06.</p>
    </div>

    <div class="diagram-container">
{build_svg()}
    </div>

{build_cards()}

    <p class="footer">
      Tiiny Image Agency • facts read from the device 2026-11-06 • generated by tools/build_architecture.py • MEASUREMENTS.md carries the detail
    </p>
  </div>
</body>
</html>
"""
    OUTPUT.write_text(html, encoding="utf-8")
    SURFACE_COPY.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(html):,} bytes)")
    print(f"  and {SURFACE_COPY} (so the surface can link to it)")
    print(f"  {len(BOXES)} boxes, {len(CARDS)} cards, no overlaps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
