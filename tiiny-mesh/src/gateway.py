#!/usr/bin/env python3
"""TiinyMesh gateway: one OpenAI-compatible endpoint for every target.

This is the piece that makes the estate usable. The panel's own gateway
serves one device; this serves all of them:

    POST /v1/chat/completions   -> routed by model id
    GET  /v1/models              -> the merged catalogue, one row per model
    GET  /v1/models/<id>         -> one model, with its target
    GET  /mesh/targets           -> every target, its health and its models
    POST /mesh/lifecycle         -> download / start / stop, on a Tiiny

Model ids are namespaced as "target/model" so two boxes that both serve
"Qwen/Qwen3.6-35B-A3B" stay distinguishable. A bare model id resolves
through the mesh's priority order.

Standard library only, like the panel it sits beside.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import unquote_plus
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh as M  # noqa: E402
import mesh_amc  # noqa: E402
import openrouter  # noqa: E402
import minimax_quota  # noqa: E402
import activity  # noqa: E402

#: The live activity monitor. One per gateway process; the sampler
#: thread fills it and the read routes serve from it. Created below,
#: once _load_mesh exists.
ACTIVITY: "activity.ActivityMonitor"

CONFIG = os.environ.get("TIINY_MESH_CONFIG", str(M.DEFAULT_CONFIG))
PORT = int(os.environ.get("TIINY_MESH_PORT", "8767"))
# The key file is overridable so a copy of this project does not share -
# or create - the live gateway's key.
KEY_FILE = os.environ.get(
    "TIINY_MESH_KEY_FILE", str(Path.home() / ".hermes" / "mesh" / "gateway_key"))
LOG_FILE = os.environ.get("TIINY_MESH_LOG", str(Path.home() / ".hermes" / "mesh" / "gateway.log"))


def _fingerprint(key: str) -> str:
    """A short, non-reversible tag for a key.

    The log is a world-readable file. Printing the key into it would put
    a bearer token on disk in the clear, so the log gets a fingerprint
    instead - enough to tell two keys apart, useless to anyone who finds
    the file.
    """
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _key():
    """The gateway's own key, so other apps can be given one."""
    try:
        with open(KEY_FILE) as fh:
            k = fh.read().strip()
        if k:
            return k
    except OSError:
        pass
    k = uuid.uuid4().hex
    try:
        os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
        with open(KEY_FILE, "w") as fh:
            fh.write(k)
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return k


def _background_path(m) -> str:
    """The user's own graphic for the dashboard background, if any."""
    for src in (m.raw.get("ui") or {}).get("background_image"), \
               (m.raw.get("theme") or {}).get("background_image"):
        if src:
            return str(src)
    return ""


def _sync_hermes_fallback(provider: str, model: str) -> bool:
    """Sync Hermes agent delegation.fallback_providers in ~/.hermes/config.yaml."""
    try:
        import re
        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if not cfg_path.exists():
            return False
        content = cfg_path.read_text(encoding="utf-8")
        pattern = r"fallback_providers:\s*\n(\s*-\s*provider:\s*[\w:-]+\s*\n\s*model:\s*[\w./-]+)"
        replacement = f"fallback_providers:\n    - provider: {provider}\n      model: {model}"
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement, content, count=1)
            tmp = cfg_path.with_suffix(".tmp")
            tmp.write_text(new_content, encoding="utf-8")
            os.replace(tmp, cfg_path)
            return True
    except Exception:
        pass
    return False


def _ui_payload(m) -> dict:
    """Everything the dashboard needs, in one read.

    Read-only and unauthenticated: it is a loopback service and the data
    is a catalogue, not a credential. The policy WRITE is authenticated.
    """
    import time as _time
    rows = m.catalogue()
    by_target: dict = {}
    for r in rows:
        by_target.setdefault(r["target"], []).append(r)

    targets = []
    act_by_target: dict = {}
    if ACTIVITY:
        try:
            for entry in ACTIVITY.snapshot(include_history=False).get("targets") or []:
                act_by_target[entry.get("target")] = entry
        except Exception:
            act_by_target = {}
    for t in m.targets:
        h = M.health(t)
        trows = by_target.get(t.id, [])
        resident = [r["model_id"] for r in trows if r.get("status") == "running"]
        npu_pct = None
        npu_total = None
        if t.kind == "tiiny":
            st, payload, _ = M._request(t.admin("/api/v1/npu/status"), t.key(), timeout=20)
            if isinstance(payload, dict):
                for dev in payload.get("devices") or []:
                    npu_total = dev.get("mem_total_mb") or npu_total
                    used = dev.get("mem_used_mb")
                    if used and npu_total:
                        npu_pct = round(used * 100.0 / npu_total, 1)
        act = act_by_target.get(t.id) or {}
        targets.append({
            "id": t.id,
            "kind": t.kind,
            "health": "up" if h["ok"] else "down",
            "http": h["http"],
            "ms": h["ms"],
            "capabilities": t.capabilities,
            "priority": t.priority,
            "models_served": len([r for r in trows if r.get("routable")]),
            "models_total": len(trows),
            "npu_used_percent": npu_pct,
            "npu_total_mb": npu_total,
            # live load, from the activity sampler
            "npu_load_percent": act.get("util_percent"),
            "npu_state": act.get("state"),
            "active_requests": act.get("active_requests"),
            "resident": resident,
            "note": t.note,
        })

    caps = {}
    for cap in ("chat", "embedding", "tts", "asr", "image_gen", "rerank",
                "vision", "ocr", "music_gen", "video_gen"):
        available = [r["mesh_id"] for r in rows if cap in (r.get("capabilities") or [])]
        if available:
            caps[cap] = {"available": available, "used_by": cap}

    ui = m.raw.get("ui") or {}
    theme = m.raw.get("theme") or {}
    bg = ui.get("background_image") or theme.get("background_image")
    accent = ui.get("accent") or theme.get("accent")

    return {
        "generated": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "theme": {
            "background_image": bg,
            "background_url": ("http://127.0.0.1:%d/ui/background" % PORT) if bg else None,
            "accent": accent,
        },
        "policy": {cap: m.policy_for(cap) for cap in
                   ("chat", "embedding", "tts", "asr", "image_gen")},
        "targets": targets,
        "pools": m.pools().get("pools", []),
        "capabilities": caps,
        "totals": {
            "targets": len(m.targets),
            "up": len([t for t in targets if t["health"] == "up"]),
            "models": len(rows),
            "chat_routable": len(m.chat_catalogue()),
            # how many capabilities have a PRIMARY set - a capability with
            # only a secondary is a fallback, not a route
            "capabilities_routed": len([
                c for c in m.policy if (m.policy.get(c) or {}).get("primary")]),
            "capabilities_with_fallback": len([
                c for c in m.policy if (m.policy.get(c) or {}).get("secondary")]),
        },
        "amc": mesh_amc.collect({"amc": m.raw.get("amc", {})}),
        "openrouter_credits": openrouter.credits(),
        "minimax_quota": minimax_quota.quota(),
        "cloud_fallback": {
            "current": "openrouter" if "openrouter" in (((m.policy.get("chat") or {}).get("secondary") or "").strip()) else "minimax" if "minimax" in (((m.policy.get("chat") or {}).get("secondary") or "").strip()) else "other",
            "model": ((m.policy.get("chat") or {}).get("secondary") or "").strip(),
        },
    }


#: GET paths that need no key. Read-only, loopback-only, and carrying no
#: credential: the dashboard page, its data, and the background image.
_PUBLIC_READS = {"/", "/ui", "/mesh/ui", "/ui/data", "/ui/background",
                 "/mesh/background", "/mesh/health", "/mesh/targets",
                 "/targets", "/mesh/catalogue", "/catalogue", "/mesh/policy",
                 "/mesh/config", "/mesh/openrouter/credits", "/mesh/credits",
                 "/mesh/amc", "/mesh/readme", "/readme", "/mesh/fallback",
                 "/mesh/minimax/quota", "/mesh/minimax", "/mesh/pools", "/pools",
                 "/mesh/activity", "/activity", "/mesh/find", "/find",
                 "/mesh/storage", "/storage"}


def _load_mesh():
    return M.Mesh.load(CONFIG)


# The monitor needs _load_mesh, so it is built here rather than at the
# top of the file.
ACTIVITY = activity.ActivityMonitor(_load_mesh)


def _parse_multipart(raw: bytes, ctype: str, encoding: str | None) -> dict:
    """Pull the fields out of a multipart/form-data body.

    The ASR endpoint takes an audio file, so the gateway has to be able
    to read a multipart body. This is deliberately minimal: it returns
    the text fields and the first file part, so a caller can re-encode
    the request upstream.
    """
    import email.parser
    import email.policy

    header = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n"
    if encoding and encoding.lower() == "gzip":
        import gzip
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        header.encode() + raw)
    out: dict = {"files": {}}
    if not msg.is_multipart():
        return out
    for part in msg.iter_parts():
        disp = part.get("Content-Disposition", "")
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            out["files"][name] = {"filename": filename,
                                  "content_type": part.get_content_type(),
                                  "data": payload}
        else:
            out[name] = payload.decode("utf-8", "replace")
    return out


def _multipart_rebuild(fields: dict) -> tuple[bytes, str]:
    """Re-encode a parsed multipart body for an upstream target."""
    import email.generator
    import email.parser
    import email.policy

    boundary = "----meshboundary7f3a2c"
    parts = []
    for key, value in fields.items():
        if key == "files":
            for name, spec in (value or {}).items():
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                    f'filename="{spec["filename"]}"\r\n'
                    f'Content-Type: {spec["content_type"]}\r\n\r\n'.encode()
                    + spec["data"] + b"\r\n")
        else:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                .encode() + str(value).encode() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post_raw(url: str, bearer: str, body: bytes, ctype: str, timeout: int = 60):
    """POST a body that is not JSON - a multipart upload, for instance."""
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        if url.startswith("https") and M._SSL is not None:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout, context=M._SSL)
        else:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout)
        with resp_ctx as resp:
            raw = resp.read()
            status = resp.status
            ctype_out = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        ctype_out = e.headers.get("Content-Type", "")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", {}
    if "json" in (ctype_out or ""):
        try:
            return status, json.loads(raw.decode()), {}
        except Exception:
            return status, raw.decode("utf-8", "replace"), {}
    return status, raw, {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # keep the console readable
        if os.environ.get("TIINY_MESH_QUIET"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    # ---------------------------------------------------------------- utils
    def _send(self, code, payload, ctype="application/json"):
        if isinstance(payload, (bytes, bytearray)):
            self._send_binary(code, bytes(payload),
                              ctype if ctype != "application/json" else "application/octet-stream")
            return
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload).encode()
        else:
            body = str(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_one_request(self):
        """Never drop a connection on an exception.

        The default handler closes the socket without a response when a
        handler raises, which looks to the client like a network fault
        rather than a bug. Answer with a 500 and the traceback instead.
        """
        try:
            super().handle_one_request()
        except Exception:
            import traceback
            detail = traceback.format_exc()
            try:
                self._send(500, {"error": "gateway handler failed",
                                 "detail": detail[-1500:]})
            except Exception:
                pass

    def _send_binary(self, code, body: bytes, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain_body(self):
        """Read and discard the request body.

        The connection is HTTP/1.1 and therefore keep-alive. A handler that
        answers without reading the body leaves those bytes in the socket,
        and the next request on that connection is parsed starting from
        them - the server sees a method line like
        '{"capability":"tts"}GET' and answers 501. One rejected write then
        breaks every later request the browser makes, which reads as an
        authentication fault rather than a framing one.

        So every early return reads the body first.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            try:
                self.rfile.read(length)
            except Exception:
                pass

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        ctype = (self.headers.get("Content-Type") or "").lower()
        raw = self.rfile.read(length)
        if "multipart/form-data" in ctype:
            return _parse_multipart(raw, ctype, self.headers.get("Content-Encoding"))
        try:
            return json.loads(raw.decode())
        except Exception:
            return {}

    def _raw_body(self):
        """The request body and its content type, for passthrough."""
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return b"", ""
        return self.rfile.read(length), (self.headers.get("Content-Type") or "")

    def _query(self) -> dict:
        """The query parameters of this request, as a plain dict.

        The mesh reads its own query string rather than pulling in a
        parser, and it URL-decodes the values because a search phrase
        arrives with spaces in it.
        """
        out: dict = {}
        if "?" not in self.path:
            return out
        query = self.path.split("?", 1)[1]
        for pair in query.split("&"):
            if not pair:
                continue
            name, _, value = pair.partition("=")
            out[unquote_plus(name)] = unquote_plus(value)
        return out

    def _authorised(self) -> bool:
        """Loopback only, and a key if one has been issued.

        The key may arrive three ways: the Authorization header (what an
        API client sends), the X-Mesh-Key header, or a `key` query
        parameter or cookie (what a page in a browser can use, because a
        fetch() from the page cannot set a header on a navigation).
        """
        host = self.client_address[0]
        if host not in ("127.0.0.1", "::1", "localhost"):
            return False
        want = os.environ.get("TIINY_MESH_KEY") or _key()
        if not want:
            return True
        given = self.headers.get("Authorization") or ""
        if given == f"Bearer {want}" or self.headers.get("X-Mesh-Key") == want:
            return True
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
        for pair in query.split("&"):
            name, _, value = pair.partition("=")
            if name == "key" and value == want:
                return True
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "mesh_key" and value == want:
                return True
        return False

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        # The dashboard page and its data are readable without a key: this
        # is a loopback service and the data is a catalogue, not a
        # credential. A browser cannot put a bearer header on a
        # navigation, so requiring one would make the page unusable.
        # Everything that CHANGES state still requires the key.
        if path not in _PUBLIC_READS and not self._authorised():
            self._send(401, {"error": "unauthorised"})
            return
        m = _load_mesh()

        if path in ("", "/v1/models", "/models"):
            data = []
            for r in m.available():
                data.append({
                    "id": r["mesh_id"],
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": r["target"],
                    # the fields a client that only knows OpenAI asks for
                    "target": r["target"],
                    "model_id": r["model_id"],
                    "status": r.get("status"),
                    "npu_usage": r.get("npu_usage"),
                    "context_window": r.get("context_window"),
                })
            self._send(200, {"object": "list", "data": data})
            return

        if path.startswith("/v1/models/"):
            want = path[len("/v1/models/"):]
            row = m.by_mesh_id(want)
            if row is None:
                self._send(404, {"error": f"no model {want}"})
                return
            self._send(200, row)
            return

        if path in ("/mesh/targets", "/targets"):
            out = []
            for t in m.targets:
                h = M.health(t)
                out.append({
                    "id": t.id,
                    "kind": h["kind"],
                    "health": "up" if h["ok"] else "down",
                    "http": h["http"],
                    "ms": h["ms"],
                    "models_served": h["models"],
                    "note": t.note,
                })
            self._send(200, {"targets": out})
            return

        if path in ("/mesh/ui", "/ui/data"):
            self._send(200, _ui_payload(m))
            return

        if path in ("/mesh/config", "/mesh/config/targets"):
            self._send(200, {
                "targets": m.raw.get("targets") or {},
                "defaults": m.defaults,
                "policy": m.policy,
            })
            return

        if path in ("/mesh/policy", "/mesh/config/policy"):
            caps = sorted(set(list(m.policy.keys()) + list(m.defaults.keys())))
            self._send(200, {
                "policy": m.policy,
                "resolved": {c: m.policy_for(c) for c in caps},
                "capabilities": caps,
            })
            return

        if path in ("/ui", "/ui/"):
            page = Path(__file__).resolve().parent / "ui" / "index.html"
            if not page.exists():
                self._send(404, {"error": "no dashboard at " + str(page)})
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return

        if path in ("/ui/background", "/mesh/background"):
            image = _background_path(m)
            if not image or not Path(image).expanduser().exists():
                self._send(404, {"error": "no background image configured"})
                return
            try:
                data = Path(image).expanduser().read_bytes()
            except OSError as e:
                self._send(404, {"error": f"cannot read the background: {e}"})
                return
            ctype = "image/png"
            if data[:2] == b"\xff\xd8":
                ctype = "image/jpeg"
            elif data[:4] == b"RIFF":
                ctype = "image/webp"
            elif data[:6] in (b"GIF87a", b"GIF89a"):
                ctype = "image/gif"
            self._send(200, data, ctype)
            return

        if path in ("/mesh/health", "/health"):
            self._send(200, {"ok": True, "targets": len(m.targets),
                              "models": len(m.available())})
            return

        if path in ("/mesh/catalogue", "/catalogue"):
            rows = m.catalogue()
            by_target = {}
            for r in rows:
                by_target.setdefault(r["target"], []).append(r)
            self._send(200, {
                "object": "list",
                "total": len(rows),
                "chat_routable": len(m.chat_catalogue()),
                "targets": [{
                    "id": t.id,
                    "kind": t.kind,
                    "priority": t.priority,
                    "capabilities": t.capabilities,
                    "models": by_target.get(t.id, []),
                } for t in m.targets],
            })
            return

        if path in ("/mesh/storage", "/storage"):
            self._send(200, m.storage())
            return

        if path.startswith("/mesh/storage/"):
            target_id = path.split("/")[3]
            self._send(200, m.storage(target_id))
            return

        if path in ("/mesh/find", "/find"):
            q = self._query()
            query = (q.get("q") or q.get("query") or "").strip()
            if not query:
                self._send(400, {"error": "find needs a query: /mesh/find?q=..."})
                return
            try:
                limit = int(q.get("limit") or 8)
            except ValueError:
                limit = 8
            self._send(200, m.find(query, q.get("type") or "", limit))
            return

        # read-only admin proxies: NPU headroom, device status, the store
        if path.startswith("/mesh/npu/") or path.startswith("/mesh/status/") \
                or path.startswith("/mesh/store/") or path.startswith("/mesh/running/"):
            kind, target_id = path.split("/")[2], path.split("/")[3]
            target = m.by_id.get(target_id)
            if target is None:
                self._send(404, {"error": f"no target {target_id}"})
                return
            routes = {
                "npu": "/api/v1/npu/status",
                "status": "/api/v1/sys/status",
                "store": "/api/v1/models/online_models",
                "running": "/api/v1/models/running",
            }
            if kind not in routes:
                self._send(404, {"error": f"no proxy {kind}"})
                return
            st, payload, _ = M._request(target.admin(routes[kind]), target.key(),
                                        timeout=30)
            self._send(st or 502, payload if payload is not None else
                       {"error": "target unreachable"})
            return

        if path in ("/mesh/openrouter/credits", "/mesh/credits"):
            import openrouter
            force = "refresh=1" in (self.path.split("?", 1) + [""])[1]
            self._send(200, openrouter.credits(force=force))
            return

        if path in ("/mesh/minimax/quota", "/mesh/minimax"):
            import minimax_quota
            force = "refresh=1" in (self.path.split("?", 1) + [""])[1]
            self._send(200, minimax_quota.quota(force=force))
            return

        if path == "/mesh/amc":
            import mesh_amc
            force = "refresh=1" in (self.path.split("?", 1) + [""])[1]
            self._send(200, mesh_amc.collect({"amc": m.raw.get("amc", {}), "force": force}))
            return

        if path in ("/mesh/readme", "/readme"):
            import mdrender
            readme_path = Path(__file__).resolve().parent / "README.md"
            if not readme_path.exists():
                self._send(404, {"error": "README.md not found"})
                return
            html = mdrender.render_markdown(readme_path.read_text(encoding="utf-8"), title="TiinyMesh Documentation")
            self._send(200, html.encode("utf-8"), ctype="text/html; charset=utf-8")
            return

        if path == "/mesh/fallback":
            chat_sec = ((m.policy.get("chat") or {}).get("secondary") or "").strip()
            current = "openrouter" if "openrouter" in chat_sec else "minimax" if "minimax" in chat_sec else "other"
            self._send(200, {
                "ok": True,
                "current": current,
                "model": chat_sec,
                "options": {
                    "openrouter": "openrouter/google/gemini-3.8-flash",
                    "minimax": "minimax/MiniMax-M3.1-Flash",
                },
            })
            return

        if path in ("/mesh/pools", "/pools"):
            self._send(200, m.pools())
            return

        if path in ("/mesh/activity", "/activity"):
            # Live "is this box working right now" telemetry. Served from
            # the sampler's rolling history, so the panel can draw a
            # sparkline without polling the appliances itself.
            snap = ACTIVITY.snapshot() if ACTIVITY else {"targets": []}
            if path == "/mesh/activity" and self.path.find("history=0") != -1:
                for entry in snap.get("targets") or []:
                    entry.pop("history", None)
            self._send(200, snap)
            return

        self._send(404, {"error": "not found", "path": path})

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        if not self._authorised():
            self._drain_body()
            self._send(401, {"error": "unauthorised"})
            return
        path = self.path.split("?")[0].rstrip("/")
        m = _load_mesh()

        if path == "/mesh/fallback":
            b = self._body()
            target_choice = str(b.get("target") or "").strip().lower()
            options = {
                "openrouter": ("openrouter/google/gemini-3.8-flash", "openrouter", "google/gemini-3.8-flash"),
                "minimax": ("minimax/MiniMax-M3.1-Flash", "minimax", "MiniMax-M3"),
            }
            if target_choice not in options:
                self._send(400, {"error": f"target must be one of: {list(options.keys())}"})
                return
            mesh_secondary, hermes_prov, hermes_mod = options[target_choice]
            res = m.set_policy("chat", secondary=mesh_secondary)
            if not res.get("ok"):
                self._send(500, res)
                return
            synced = _sync_hermes_fallback(hermes_prov, hermes_mod)
            self._send(200, {
                "ok": True,
                "current": target_choice,
                "model": mesh_secondary,
                "hermes_synced": synced,
                "hermes_fallback": {"provider": hermes_prov, "model": hermes_mod},
            })
            return

        if path in ("/mesh/policy", "/mesh/config/policy"):
            b = self._body()
            capability = str(b.get("capability") or "").strip()
            if not capability:
                self._send(400, {"error": "capability is required"})
                return
            # absent -> None (leave that slot alone); "" -> clear it
            primary = b["primary"] if "primary" in b else None
            secondary = b["secondary"] if "secondary" in b else None
            primary = None if primary is None else str(primary).strip()
            secondary = None if secondary is None else str(secondary).strip()
            result = m.set_policy(capability, primary, secondary)
            self._send(200 if result.get("ok") else 400, result)
            return

        if path in ("/mesh/config", "/mesh/config/policy/targets"):
            b = self._body()
            saved = m.save_config(b)
            self._send(200 if saved.get("ok") else 400, saved)
            return

        if path in ("/ui/background", "/mesh/background"):
            body, ctype = self._raw_body()
            if not body:
                self._send(400, {"error": "no image bytes in the request"})
                return
            if len(body) > 12 * 1024 * 1024:
                self._send(413, {"error": "the image is larger than 12 MB"})
                return
            kind = (ctype or "").lower()
            if not any(k in kind for k in ("image/png", "image/jpeg", "image/webp",
                                           "image/gif")):
                self._send(415, {"error": "send a png, jpeg, webp or gif"})
                return
            ext = {"image/png": ".png", "image/jpeg": ".jpg",
                   "image/webp": ".webp", "image/gif": ".gif"}.get(kind, ".img")
            saved = m.set_background(body, ext)
            self._send(200 if saved.get("ok") else 400, saved)
            return

        if path in ("/v1/embeddings", "/embeddings"):
            b = self._body()
            want = b.get("model") or ""
            target, upstream, how = m.resolve_capability("embedding", want)
            if target is None:
                self._send(404, {"error": "no target serves embeddings",
                                 "hint": "GET /mesh/catalogue lists every model"})
                return
            b["model"] = upstream
            st, payload, _ = M._request(
                target.base_url.rstrip("/") + "/embeddings",
                target.key(), method="POST", body=b, timeout=120)
            if isinstance(payload, dict):
                payload.setdefault("mesh_target", target.id)
                payload["mesh_route"] = {"target": target.id, "requested": want,
                                         "served": upstream, "how": how}
                # the dimension is part of the contract: a RAG index breaks
                # if the route shifts underneath it
                dim = None
                try:
                    dim = len(payload["data"][0]["embedding"])
                except Exception:
                    dim = M.embed_dimension(upstream) if hasattr(M, "embed_dimension") else None
                if dim:
                    payload["mesh_route"]["dimension"] = dim
            self._send(st or 502, payload)
            return

        if path in ("/v1/audio/speech", "/audio/speech"):
            b = self._body()
            want = b.get("model") or ""
            target, upstream, how = m.resolve_capability("tts", want)
            if target is None:
                self._send(404, {"error": "no target serves text-to-speech"})
                return
            b["model"] = upstream
            # A Tiiny TTS model does not accept an OpenAI-style voice name.
            # "default" becomes a voice the model actually has.
            if M.CAP is not None:
                b["voice"] = M.CAP.resolve_voice(upstream, b.get("voice", ""))
            result, borrow = m.call_with_borrow(
                target, upstream,
                lambda: M._request(
                    target.base_url.rstrip("/") + "/audio/speech",
                    target.key(), method="POST", body=b, timeout=180))
            if result is None:
                self._send(502, borrow or {"error": "could not load the model"})
                return
            st, payload, headers = result
            if isinstance(payload, (bytes, bytearray)):
                self._send_binary(st or 200, bytes(payload), "audio/wav")
                return
            if isinstance(payload, dict):
                payload.setdefault("mesh_target", target.id)
                payload["mesh_route"] = {"target": target.id, "requested": want,
                                         "served": upstream, "how": how,
                                         "borrowed": bool(borrow)}
            self._send(st or 502, payload)
            return

        if path in ("/v1/audio/transcriptions", "/audio/transcriptions"):
            fields = self._body()
            want = fields.get("model") or ""
            target, upstream, how = m.resolve_capability("asr", want)
            if target is None:
                self._send(404, {"error": "no target serves transcription"})
                return
            fields["model"] = upstream
            body, ctype = _multipart_rebuild(fields)
            result, borrow = m.call_with_borrow(
                target, upstream,
                lambda: _post_raw(
                    target.base_url.rstrip("/") + "/audio/transcriptions",
                    target.key(), body, ctype, timeout=180))
            if result is None:
                self._send(502, borrow or {"error": "could not load the model"})
                return
            st, payload, _ = result
            if isinstance(payload, dict):
                payload.setdefault("mesh_target", target.id)
                payload["mesh_route"] = {"target": target.id, "requested": want,
                                         "served": upstream, "how": how}
            self._send(st or 502, payload)
            return

        if path in ("/v1/images/generations", "/images/generations"):
            b = self._body()
            want = b.get("model") or ""
            target, upstream, how = m.resolve_capability("image_gen", want)
            if target is None:
                self._send(404, {"error": "no target serves image generation"})
                return
            b["model"] = upstream
            result, borrow = m.call_with_borrow(
                target, upstream,
                lambda: M._request(
                    target.base_url.rstrip("/") + "/images/generations",
                    target.key(), method="POST", body=b, timeout=300))
            if result is None:
                self._send(502, borrow or {"error": "could not load the model"})
                return
            st, payload, _ = result
            if isinstance(payload, dict):
                payload.setdefault("mesh_target", target.id)
                payload["mesh_route"] = {"target": target.id, "requested": want,
                                         "served": upstream, "how": how}
            self._send(st or 502, payload)
            return


        if path == "/mesh/policy":
            b = self._body()
            capability = b.get("capability")
            if not capability:
                self._send(400, {"error": "capability is required"})
                return
            result = m.set_policy(capability,
                                   primary=b.get("primary", ""),
                                   secondary=b.get("secondary", ""))
            self._send(200 if result.get("ok") else 400, result)
            return

        if path == "/mesh/lifecycle":
            b = self._body()
            action = b.get("action")
            model = b.get("model")
            target = b.get("target")
            if action == "boot":
                if not target:
                    self._send(400, {"error": "target is required"})
                    return
                self._send(200, m.boot_target(target))
                return
            if not (action and model and target):
                self._send(400, {"error": "action, model and target are required"})
                return
            if action not in ("download", "start", "stop"):
                self._send(400, {"error": f"unknown action {action}"})
                return
            self._send(200, m.lifecycle(target, model, action))
            return

        if path in ("/v1/chat/completions", "/chat/completions"):
            b = self._body()
            want = b.get("model") or ""
            result = m.chat(want, b, timeout=300)
            if not result.get("ok"):
                status = result.get("status") or 502
                payload = result.get("payload")
                if payload is None:
                    payload = {"error": result.get("error", "request failed"),
                               "detail": result.get("detail")}
                    status = 502 if status is None else status
                self._send(status, payload)
                return
            self._send(result["status"], result["payload"])
            return

        self._send(404, {"error": "not found", "path": path})

    def do_DELETE(self):
        if not self._authorised():
            self._drain_body()
            self._send(401, {"error": "unauthorised"})
            return
        path = self.path.split("?")[0].rstrip("/")
        m = _load_mesh()
        if path in ("/ui/background", "/mesh/background"):
            self._send(200, m.clear_background())
            return
        self._send(404, {"error": "not found", "path": path})


def _restore_worker():
    """Re-load the models the appliances should keep resident.

    A Tiiny unloads everything on reboot. The gateway starts at login and
    the boxes may still be coming up, so this waits, retries, and then
    loads what is missing. It runs in a thread so the gateway serves
    immediately rather than blocking on a sleeping appliance.
    """
    for attempt in range(6):
        try:
            m = _load_mesh()
            wanted = [t for t in m.targets if getattr(t, "keep_resident", None)]
            if not wanted:
                return
            results = m.restore()
            pending = [r for r in results if r.get("action") == "start" and not r.get("ok")]
            if not pending:
                for r in results:
                    sys.stderr.write(
                        f"[restore] {r['target']} {r['model']}: {r['action']}\n")
                for r in results:
                    if r.get("action") == "start":
                        status = m.wait_resident(r["target"], r["model"], wait_s=120)
                        sys.stderr.write(
                            f"[restore] {r['target']} {r['model']} -> {status}\n")
                return
            sys.stderr.write(
                f"[restore] attempt {attempt + 1}: {len(pending)} target(s) not up yet\n")
        except Exception as e:
            sys.stderr.write(f"[restore] attempt {attempt + 1} failed: {e}\n")
        time.sleep(20)


def _credits_worker():
    """Background daily refresh of OpenRouter credits."""
    import openrouter
    while True:
        try:
            res = openrouter.credits(force=True)
            if res.get("ok"):
                sys.stderr.write(f"[credits] refreshed OpenRouter credits ({res.get('scope')})\n")
        except Exception as e:
            sys.stderr.write(f"[credits] refresh failed: {e}\n")
        time.sleep(86400)


def _minimax_quota_worker():
    """Background periodic monitor of MiniMax Token Plan quota."""
    import minimax_quota
    while True:
        try:
            q = minimax_quota.quota(force=True)
            if q.get("ok"):
                if q.get("is_exhausted"):
                    m = _load_mesh()
                    sec = ((m.policy.get("chat") or {}).get("secondary") or "").strip()
                    if "openrouter" not in sec:
                        sys.stderr.write(
                            "[quota:minimax] quota exhausted -> auto-switching fallback to OpenRouter Gemini\n")
                        m.set_policy("chat", secondary="openrouter/google/gemini-3.8-flash")
                        _sync_hermes_fallback("openrouter", "google/gemini-3.8-flash")
                else:
                    sys.stderr.write(
                        f"[quota:minimax] healthy (weekly: {q.get('weekly_remaining_percent')}%, "
                        f"5h: {q.get('interval_remaining_percent')}%)\n")
        except Exception as e:
            sys.stderr.write(f"[quota:minimax] poll error: {e}\n")
        time.sleep(300)


def main():
    if not os.path.exists(CONFIG):
        sys.stderr.write(f"no mesh config at {CONFIG}\n")
        return 2
    key = _key()
    m = _load_mesh()
    # The port may already be taken - a second gateway is a common
    # mistake and a traceback does not say so.
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        if e.errno == 48:
            sys.stderr.write(
                f"port {PORT} is already in use - is a gateway already running?\n"
                f"  TIINY_MESH_PORT=<other> picks a different one\n")
            return 1
        raise
    sys.stderr.write(f"TiinyMesh gateway on http://127.0.0.1:{PORT}\n")
    sys.stderr.write(f"  targets: {len(m.targets)}   chat-routable models: {len(m.available())}\n")
    sys.stderr.write(f"  key fingerprint: {_fingerprint(key)}   (in {KEY_FILE})\n")
    sys.stderr.write("  point an app at this URL with that key.\n")

    # The auto-loader is opt-out. During a delegated coding run the
    # manager decides what stays resident, and a loader that puts the
    # appliances back to their default models will evict the specialist
    # mid-batch. Set "auto_restore": false in the config to switch it off;
    # the default is unchanged for every other use.
    auto_restore = m.raw.get("auto_restore", True)
    restore_targets = [t.id for t in m.targets if getattr(t, "keep_resident", None)]
    if not auto_restore:
        restore_targets = []
        sys.stderr.write("[restore] disabled by config (auto_restore=false)\n")
    if restore_targets:
        sys.stderr.write(f"  restoring resident models on: {', '.join(restore_targets)}\n")
        threading.Thread(target=_restore_worker, daemon=True).start()

    threading.Thread(target=_credits_worker, daemon=True).start()
    threading.Thread(target=_minimax_quota_worker, daemon=True).start()
    # The activity sampler: polls each appliance's NPU telemetry on a
    # timer so the panel can show whether a box is working right now.
    # A failure here must never take the gateway down, so it lives in
    # its own thread and swallows its own errors.
    threading.Thread(target=ACTIVITY.run_forever, daemon=True).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
