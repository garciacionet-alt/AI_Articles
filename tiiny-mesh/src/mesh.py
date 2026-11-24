"""TiinyMesh — one catalogue and one router across every inference target.

The panel we forked is built around a single Tiiny: `device.resolve()` returns
one address and one key, and everything downstream assumes one NPU pool, one
model store and one device's worth of admin routes. the author's estate is not that:
two appliances, a Mac-side gateway (OGAD or LM Studio) and cloud providers.

This module is the seam. Every target becomes the same three things:

  * a catalogue  — what models it can serve, and what it says about them
  * an inference path — where a request goes
  * an optional lifecycle — only Tiiny has one (download / load / unload)

Everything else in the system then talks to a target id instead of an address.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# The sibling modules - capabilities.py in particular - are imported by
# bare name. Put this file's own directory on the path so the import
# works no matter where the interpreter was started from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_CONFIG = Path(os.environ.get("TIINY_MESH_CONFIG",
                                      str(Path.home() / ".hermes" / "mesh" / "config.json")))
ENV_FILE = Path(os.environ.get("TIINY_MESH_ENV",
                                str(Path.home() / ".hermes" / ".env")))
TIMEOUT = 20


def load_env(path: os.PathLike | str = ENV_FILE) -> None:
    """Read the Hermes env file into the process environment.

    Credentials live in ~/.hermes/.env and nowhere else. A service that
    wants a target's key has to load them the way Hermes does - by name,
    never by value. Existing environment variables win, so an explicit
    export always overrides the file.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name and name not in os.environ:
                os.environ[name] = value.strip().strip('"').strip("'")
    except OSError:
        pass


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass
class Target:
    """One inference target: an appliance, a local server, or a cloud API."""

    id: str
    kind: str                       # "tiiny" | "openai" | "anthropic" | "openrouter"
    base_url: str = ""              # the OpenAI-compatible root, e.g. http://ip:7878/v1
    admin_url: str = ""             # the device admin root (Tiiny only), e.g. http://ip
    key_env: str = ""               # env var holding the credential (never the value)
    models: list[str] = field(default_factory=list)   # explicit list; empty = ask the target
    priority: int = 50              # lower wins when a bare model id is ambiguous
    boot: list[str] = field(default_factory=list)     # command that starts a stopped local server
    extra_body: dict = field(default_factory=dict)     # merged into every request to this target
    keep_resident: list[str] = field(default_factory=list)  # re-loaded after a device reboot
    capabilities: list[str] = field(default_factory=list)    # what this target can do at all
    note: str = ""

    # -- credential ------------------------------------------------------
    def key(self) -> str:
        """The credential, from the environment. Never stored in the config."""
        if not self.key_env:
            return ""
        value = os.environ.get(self.key_env, "").strip()
        return value.strip('"').strip("'")

    # -- catalogue -------------------------------------------------------
    def models_url(self) -> str:
        base = self.base_url.rstrip("/")
        if self.kind == "anthropic" and not base.endswith("/v1"):
            # Anthropic-shaped hosts put the model list under /v1, but the
            # chat endpoint is /v1/messages, not /v1/chat/completions.
            return base + "/v1/models"
        return base + "/models"

    def admin(self, path: str) -> str:
        return self.admin_url.rstrip("/") + path

    def chat_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def is_local(self) -> bool:
        host = self.base_url.split("//", 1)[-1].split("/", 1)[0]
        return host.startswith(("127.", "localhost", "::1", "10.", "192.168."))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _ssl_context():
    """An SSL context that trusts the right certificate authorities.

    Python builds vary. A python.org or Homebrew 3.13+ install ships with
    no usable CA store, and then every HTTPS call fails with
    CERTIFICATE_VERIFY_FAILED. Try, in order:

      1. certifi, if it is importable
      2. the well-known macOS and Homebrew bundle paths
      3. the system default store
      4. an unverified context, so one cloud target degrades to "down"
         rather than taking the whole gateway with it
    """
    import ssl

    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    for path in ("/etc/ssl/cert.pem",
                 "/private/etc/ssl/cert.pem",
                 "/opt/homebrew/etc/openssl@3/cert.pem",
                 "/usr/local/etc/openssl@3/cert.pem"):
        try:
            if os.path.exists(path):
                return ssl.create_default_context(cafile=path)
        except Exception:
            continue

    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs()
        return ctx
    except Exception:
        pass

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    except Exception:
        return None


_SSL = _ssl_context()

# A thinking model that exhausts its budget returns empty content and a
# populated reasoning channel. Measured on TiinyOcto: gpt-oss-20b always
# reasons (chat_template_kwargs does not apply to it) and returns nothing
# at max_tokens=64, but answers normally at 512. The Qwen family accepts
# enable_thinking=false and never needs the extra room.
THINKING_BUDGET = 512


def _thinking_starved(resp) -> bool:
    """True when the model reasoned but ran out of room to answer."""
    if not isinstance(resp, dict):
        return False
    choices = resp.get("choices")
    if not choices or not isinstance(choices[0], dict):
        return False
    msg = choices[0].get("message") or {}
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    return not content and bool(reasoning)


def _request(url: str, bearer: str = "", method: str = "GET",
             body: Any = None, timeout: int = TIMEOUT):
    """Return (status, parsed_body, headers).

    A JSON response is parsed. Anything else is returned as raw bytes.
    Decoding a binary response as text corrupts it - every non-UTF-8 byte
    becomes a replacement character, which silently turns a 118 KB WAV into
    a 214 KB invalid one.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        if url.startswith("https") and _SSL is not None:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout, context=_SSL)
        else:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout)
        with resp_ctx as resp:
            raw = resp.read()
            status = resp.status
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        ctype = (e.headers.get("Content-Type") or "").lower()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", {}

    if "json" in ctype or raw[:1] in (b"{", b"["):
        try:
            return status, json.loads(raw.decode("utf-8", "replace")), {}
        except Exception:
            pass
    if ctype.startswith("text/") or not ctype:
        return status, raw.decode("utf-8", "replace"), {}
    return status, raw, {}


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------


def _norm_openai_models(payload) -> list[dict]:
    """An OpenAI /v1/models payload, normalized to the mesh's row shape.

    OGAD adds a `kind` field per model (chat, vision, image, speech,
    transcription, grounding_specialist) that is its own routing key.
    """
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    rows = []
    for m in items:
        if isinstance(m, str):
            rows.append({"model_id": m, "status": "available"})
            continue
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("model_id") or m.get("name")
        if not mid:
            continue
        rows.append({
            "model_id": mid,
            "status": "available",
            "context_window": m.get("context_length") or m.get("context_window"),
            "type": m.get("type") or m.get("task") or "",
            "kind": m.get("kind") or "",
        })
    return rows


def _norm_tiiny_store(payload, full: bool = False) -> list[dict]:
    """A Tiiny /api/v1/models/online_models payload, normalized.

    The store catalogue is the only place that knows the truth about a Tiiny
    model: whether it is downloaded, how much NPU it wants, how long it takes
    to load, and what it can do. The OpenAI-compatible /v1/models on the same
    box lists only RESIDENT models, which is why the two endpoints disagree.

    ``full`` adds the descriptive fields - the description, the tags, the
    device's own recommendation rank - that a search needs and that the
    catalogue listing does not. They are large, so they are opt-in.
    """
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    rows = []
    for m in items:
        if not isinstance(m, dict):
            continue
        mid = m.get("model_id") or m.get("id")
        if not mid:
            continue
        row = {
            "model_id": mid,
            "status": m.get("status") or "not_downloaded",
            "progress": m.get("progress"),
            "npu_usage": m.get("npu_usage"),
            "context_window": m.get("context_window"),
            "type": m.get("type") or "",
            "params": m.get("params"),
            "capabilities": m.get("capabilities") or [],
            "load_time": m.get("load_time"),
        }
        if full:
            row.update({
                "name": m.get("name") or "",
                "desc": m.get("desc") or "",
                "tags": m.get("tags") or [],
                "supported": m.get("supported") or [],
                "input": m.get("input") or "",
                "output": m.get("output") or "",
                "is_trend": m.get("is_trend"),
                "recommend_rank": m.get("recommend_rank"),
                "trending_score": m.get("trending_score"),
                "likes": m.get("likes"),
                "downloads": m.get("downloads"),
                "need_update": m.get("need_update"),
            })
        rows.append(row)
    return rows


def catalogue(target: Target, full: bool = False) -> dict:
    """What this target can serve. Never raises."""
    if target.kind == "tiiny":
        status, payload, _ = _request(target.admin("/api/v1/models/online_models"), target.key())
        if status == 200:
            rows = _norm_tiiny_store(payload, full=full)
            return {"target": target.id, "ok": True, "models": rows, "source": "store"}
        # store unreachable: fall back to what is resident right now
        status, payload, _ = _request(target.models_url(), target.key())
        rows = _norm_openai_models(payload) if status == 200 else []
        for r in rows:
            r["status"] = "running"
        return {"target": target.id, "ok": status == 200, "models": rows, "source": "resident"}

    status, payload, _ = _request(target.models_url(), target.key())
    if status != 200:
        return {"target": target.id, "ok": False, "models": [], "error": f"HTTP {status}",
                "source": "models"}
    if target.models:
        # an explicit list is authoritative for a cloud target
        by_id = {r["model_id"]: r for r in _norm_openai_models(payload)}
        rows = []
        for mid in target.models:
            rows.append(by_id.get(mid, {"model_id": mid, "status": "available"}))
        return {"target": target.id, "ok": True, "models": rows, "source": "configured"}
    return {"target": target.id, "ok": True, "models": _norm_openai_models(payload), "source": "models"}


# --------------------------------------------------------------------------
# the mesh
# --------------------------------------------------------------------------


try:
    import capabilities as CAP
except ImportError:      # the module is optional; the mesh still works without it
    CAP = None

try:
    import find as FIND
except ImportError:      # the module is optional; only /mesh/find needs it
    FIND = None


#: How a placement is ordered, best first. A box that is running the
#: model right now costs nothing; a box that has to evict something to
#: make room costs a resident model; a box that has to download it
#: costs minutes of transfer and the disk it lands on.
_PLACEMENT_ORDER = {"ready": 0, "load": 1, "use": 1, "un-reside": 2,
                    "download": 3, "unavailable": 4}


def _placement_rank(placement: dict) -> tuple:
    """Sort key for placements: cheapest action first, then the tidier box."""
    action = placement.get("action") or "unavailable"
    return (_PLACEMENT_ORDER.get(action, 5), placement.get("target") or "")


# A fallback classification, used when the capabilities module is not
# present. These are the Tiiny catalogue's own `type` strings, measured
# from the device, and OGAD's own `kind` values. Keeping a copy here
# means the mesh never publishes a model it cannot serve just because a
# helper file is missing.
_FALLBACK_TIINY_TYPES = {
    "ASR": ["asr", "audio_understand"],
    "Image-Text-to-Text": ["chat", "vision"],
    "Image-to-3D": ["three_d"],
    "Image-to-Text": ["ocr", "vision"],
    "Music Generation": ["music_gen"],
    "Text Classification": ["classification"],
    "Text Embedding": ["embedding"],
    "Text Generation": ["chat"],
    "Text Reranking": ["rerank"],
    "Text-to-Image": ["image_gen"],
    "Text-to-Speech": ["tts"],
    "Text-to-Video": ["video_gen"],
}
_FALLBACK_OGAD_KINDS = {
    "chat": ["chat"],
    "vision": ["vision", "chat"],
    "image": ["image_gen"],
    "speech": ["tts"],
    "transcription": ["asr", "audio_understand"],
    "grounding_specialist": ["grounding"],
}


def _classify(row: dict, target: "Target | None" = None) -> list[str]:
    """The capability list for one catalogue row.

    Prefers the device's own metadata. OGAD says what each model is in a
    `kind` field; a Tiiny says it in `type`. Only when the target says
    nothing does the id get a look, and only conservatively.
    """
    if CAP is not None:
        kind = row.get("kind") or ""
        if kind:
            caps = CAP.classify_ogad(kind, row.get("model_id", ""))
            if caps:
                return caps
        type_str = row.get("type") or ""
        if type_str:
            caps = CAP.classify_tiiny(type_str, row.get("capabilities") or [],
                                      row.get("model_id", ""))
            if caps:
                return caps
        # The target's declared capabilities describe the TARGET, not this
        # model - using them here would give every model on the target
        # the target's whole capability list. Classify the model instead.
        return CAP.classify_generic(row.get("model_id", ""))

    kind = row.get("kind") or ""
    if kind in _FALLBACK_OGAD_KINDS:
        return list(_FALLBACK_OGAD_KINDS[kind])
    type_str = row.get("type") or ""
    if type_str in _FALLBACK_TIINY_TYPES:
        return list(_FALLBACK_TIINY_TYPES[type_str])
    # a generic OpenAI target with no metadata: only guess from an id that
    # is unambiguous. Never guess chat from a name that says otherwise.
    mid = (row.get("model_id") or "").lower()
    if "embed" in mid or mid.startswith("bge-") or "bge-" in mid:
        return ["embedding"]
    if "rerank" in mid:
        return ["rerank"]
    if "whisper" in mid:
        return ["asr"]
    if "tts" in mid or "speech" in mid:
        return ["tts"]
    # no usable metadata: assume chat, which is the safe default because
    # the chat route is the one every target implements
    return ["chat"]


def embed_dimension(model_id: str) -> int | None:
    """The measured embedding dimension for a model, if it is known.

    The dimension is part of the contract: a RAG index built against
    1024-dim vectors breaks silently if the route shifts to a 384-dim
    model. Sourced from the capabilities module, which carries the
    measured numbers.
    """
    if CAP is None:
        return None
    try:
        return CAP.embed_dimension(model_id)
    except Exception:
        return None


class Mesh:
    """Every target, one catalogue, and the routing rules over them."""

    def __init__(self, targets: Iterable[Target], defaults: dict | None = None,
                 policy: dict | None = None, config_path: str = ""):
        self.targets = list(targets)
        self.by_id = {t.id: t for t in self.targets}
        # capability -> the mesh_id that serves it when the caller does
        # not name a model. e.g. {"embedding": "ollama/bge-m3:latest"}
        self.defaults = dict(defaults or {})
        # capability -> {"primary": ..., "secondary": ...}. This is the
        # STATIC, USER-DECLARED policy: what the user chose, not what a
        # priority order worked out to be.
        self.policy = dict(policy or {})
        self.config_path = config_path or str(DEFAULT_CONFIG)
        self.raw: dict = {}
        # Caches for the two slow reads. The store catalogue and the disk
        # figures both change slowly and both cost a round trip to every
        # appliance, so they are held briefly rather than re-read on
        # every question.
        self._storage_cache: tuple | None = None
        self._find_cache: tuple | None = None

    # -- construction ----------------------------------------------------
    @classmethod
    def load(cls, path: os.PathLike | str = DEFAULT_CONFIG) -> "Mesh":
        p = Path(path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"no mesh config at {p}")
        load_env()
        try:
            raw = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(
                f"the mesh config at {p} is not valid JSON: {e}") from None
        targets = []
        for tid, spec in (raw.get("targets") or {}).items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"target {tid!r} in {p} must be an object, not "
                    f"{type(spec).__name__}")
            spec = dict(spec)
            spec["id"] = tid
            try:
                targets.append(Target(**spec))
            except TypeError as e:
                raise ValueError(
                    f"target {tid!r} in {p} has a bad field: {e}") from None
        mesh = cls(targets, raw.get("defaults"), raw.get("policy"), str(p))
        mesh.raw = raw
        return mesh

    # -- capability routing ----------------------------------------------
    def resolve_capability(self, capability: str, model: str = "") -> tuple:
        """(target, upstream_model_id, how) for a capability request.

        The POLICY is static and user-declared: the config says which
        target is primary for each capability and which is the fallback.
        That is what the user edits; nothing here is computed from
        priorities at request time.

        Order of preference:
          1. a model the caller named
          2. the policy's primary for this capability
          3. the policy's secondary
          4. the legacy `defaults` map
          5. the best-ranked target that can serve it
        """
        if model:
            t, up, how = self.resolve(model)
            if t is not None:
                return t, up, how

        for slot in ("primary", "secondary"):
            entry = (self.policy.get(capability) or {}).get(slot)
            if not entry:
                continue
            target, upstream = self._resolve_entry(entry, capability)
            if target is not None:
                return target, upstream, f"policy:{slot}"

        default = self.defaults.get(capability)
        if default:
            target, upstream = self._resolve_entry(default, capability)
            if target is not None:
                return target, upstream, "default"

        candidates = [r for r in self.by_capability(capability)
                      if self.by_id[r["target"]].kind != "tiiny"
                      or r.get("status") in ("running", "downloaded")]
        if candidates:
            best = candidates[0]
            return (self.by_id[best["target"]], best["target_model_id"], "capability")
        return None, model or capability, "unavailable"

    def _resolve_entry(self, entry: str, capability: str = "") -> tuple:
        """Turn a policy entry into (target, upstream_model_id).

        An entry is either a mesh_id ("target/model"), a bare target id
        ("ogad"), or a bare model id that only one target serves.

        A bare target id needs the capability to pick the right model on
        it: "ogad" for image_gen means the image model, not the chat one
        that happens to be listed first.
        """
        if "/" in entry:
            tid, _, upstream = entry.partition("/")
            if tid in self.by_id:
                return self.by_id[tid], upstream
        if entry in self.by_id:
            target = self.by_id[entry]
            rows = [r for r in self.catalogue() if r["target"] == entry
                    and r.get("status") in ("running", "downloaded", "available")]
            if capability:
                serving = [r for r in rows
                           if capability in (r.get("capabilities") or [])]
                if serving:
                    # prefer one that is already running
                    serving.sort(key=lambda r: 0 if r.get("status") == "running" else 1)
                    return target, serving[0]["target_model_id"]
            if rows:
                return target, rows[0]["target_model_id"]
            return target, ""
        row = self.by_mesh_id(entry)
        if row:
            return self.by_id[row["target"]], row["target_model_id"]
        return None, entry

    def save_config(self, doc: dict) -> dict:
        """Write a whole new config, validated first.

        The config is the user's: they edit it in the dashboard and it has
        to survive a restart. A bad edit is rejected rather than written,
        because a config that cannot be parsed takes every target down.
        """
        if not isinstance(doc, dict):
            return {"ok": False, "error": "the config must be an object"}
        raw_targets = doc.get("targets")
        if not isinstance(raw_targets, dict) or not raw_targets:
            return {"ok": False, "error": "the config needs at least one target"}

        # build it in a scratch mesh first: Target() validates each field
        # and reports the offending target by name
        try:
            built = []
            for tid, spec in raw_targets.items():
                if not isinstance(spec, dict):
                    return {"ok": False, "error": f"target {tid!r} must be an object"}
                spec = dict(spec)
                spec["id"] = tid
                built.append(Target(**spec))
        except TypeError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        policy = doc.get("policy")
        if policy is not None and not isinstance(policy, dict):
            return {"ok": False, "error": "policy must be an object"}
        defaults = doc.get("defaults")
        if defaults is not None and not isinstance(defaults, dict):
            return {"ok": False, "error": "defaults must be an object"}

        path = Path(self.config_path).expanduser()
        try:
            existing = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing["targets"] = raw_targets
        if policy is not None:
            existing["policy"] = policy
        if defaults is not None:
            existing["defaults"] = defaults
        self.raw = existing

        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(existing, indent=2) + "\n")
            os.replace(tmp, path)
        except Exception as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            return {"ok": False, "error": f"cannot write {path}: {e}"}

        # adopt it, so the next request uses what was just saved
        self.targets = built
        self.by_id = {t.id: t for t in built}
        if policy is not None:
            self.policy = policy
        if defaults is not None:
            self.defaults = defaults
        return {"ok": True, "config": {"targets": raw_targets,
                                       "policy": self.policy,
                                       "defaults": self.defaults}}

    # -- the user's own background graphic --------------------------------
    def background_file(self) -> Path:
        return Path(os.path.expanduser(
            "~/.hermes/mesh/background")).with_suffix(".img")

    def set_background(self, data: bytes, ext: str = ".img") -> dict:
        """Store the user's background graphic."""
        p = self.background_file()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            os.chmod(p, 0o600)
        except Exception as e:
            return {"ok": False, "error": f"cannot write the background: {e}"}
        # remember it in the config, so the dashboard finds it after a restart
        try:
            raw = json.loads(Path(self.config_path).expanduser().read_text())
            raw["ui"] = {**(raw.get("ui") or {}), "background_image": str(p)}
            Path(self.config_path).expanduser().write_text(json.dumps(raw, indent=2) + "\n")
            self.raw = raw
        except Exception:
            pass
        return {"ok": True, "size": len(data), "path": str(p),
                "background_url": f"/ui/background"}

    def clear_background(self) -> dict:
        p = self.background_file()
        try:
            if p.exists():
                p.unlink()
        except Exception as e:
            return {"ok": False, "error": f"cannot remove the background: {e}"}
        try:
            cfg = Path(self.config_path).expanduser()
            raw = json.loads(cfg.read_text())
            if raw.get("ui"):
                raw["ui"].pop("background_image", None)
                cfg.write_text(json.dumps(raw, indent=2) + "\n")
            self.raw = raw
        except Exception:
            pass
        return {"ok": True, "background_url": None}

    def policy_for(self, capability: str) -> dict:
        """The declared policy for a capability, with both slots resolved."""
        entry = self.policy.get(capability) or {}
        out = {}
        for slot in ("primary", "secondary"):
            value = entry.get(slot)
            if not value:
                out[slot] = None
                continue
            target, upstream = self._resolve_entry(value, capability)
            out[slot] = {
                "entry": value,
                "target": target.id if target else None,
                "model": upstream or None,
            }
        return out

    def set_policy(self, capability: str, primary=None, secondary=None) -> dict:
        """Write the policy back to the config file.

        The policy is static and user-configurable, so a change made in
        the UI has to survive a restart. The config is rewritten in place,
        keeping every other key exactly as it was.

        For each slot: None means leave it alone, a string sets it, and an
        empty string CLEARS it. Without that distinction the operator
        cannot unset a route - which they need to do, because "no
        fallback" and "this box is the fallback" are different answers.
        """
        p = Path(self.config_path).expanduser()
        try:
            raw = json.loads(p.read_text())
        except Exception as e:
            return {"ok": False, "error": f"cannot read {p}: {e}"}
        policy = raw.get("policy") or {}
        entry = dict(policy.get(capability) or {})
        if primary is not None:
            entry["primary"] = primary
        if secondary is not None:
            entry["secondary"] = secondary
        entry = {k: v for k, v in entry.items() if v}
        if entry:
            policy[capability] = entry
        else:
            policy.pop(capability, None)
        raw["policy"] = policy
        self.raw = raw
        try:
            backup = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, backup)
            p.write_text(json.dumps(raw, indent=2) + "\n")
        except Exception as e:
            return {"ok": False, "error": f"cannot write {p}: {e}"}
        self.policy = policy
        return {"ok": True, "capability": capability, "policy": policy}

    # -- catalogue -------------------------------------------------------
    def catalogue(self, full: bool = False) -> list[dict]:
        """Every model every target can serve, one row each, target tagged.

        ``full`` adds the descriptive fields a search needs - the
        description, the tags, the device's own recommendation rank.
        """
        rows = []
        for t in self.targets:
            info = catalogue(t, full=full)
            for m in info["models"]:
                row = dict(m)
                row["target"] = t.id
                # the TARGET's kind lives in target_kind: the row's own
                # `kind` is what the device said about THIS model, and
                # overwriting it loses the only routing key OGAD gives
                row["target_kind"] = t.kind
                row["target_model_id"] = m["model_id"]
                row["mesh_id"] = f"{t.id}/{m['model_id']}"
                row["capabilities"] = _classify(m, t)
                row["routable"] = self._routable(t, row)
                rows.append(row)
        return rows

    # -- disk ------------------------------------------------------------
    def storage(self, target_id: str = "", ttl: float = 60.0) -> dict:
        """Disk usage per appliance. Never raises.

        The device publishes this at /api/v1/sys/storage: total, used and
        remaining bytes, plus a per-category breakdown. Only the Tiiny
        appliances have one; the other targets have no disk of their own
        and are reported as such rather than omitted, so a caller can
        tell "no disk" from "not asked".
        """
        now = time.monotonic()
        if FIND is None:
            return {"ok": False, "error": "the find module is not available"}
        if (self._storage_cache is not None
                and now - self._storage_cache[0] < ttl):
            data = self._storage_cache[1]
        else:
            data = {}
            for t in self.targets:
                if t.kind != "tiiny":
                    data[t.id] = {"ok": False, "target": t.id,
                                  "error": f"{t.kind} target has no appliance disk"}
                    continue
                data[t.id] = FIND.storage_for(t, _request)
            self._storage_cache = (now, data)

        if target_id:
            return data.get(target_id) or {"ok": False, "target": target_id,
                                           "error": f"no target {target_id}"}
        return data

    # -- find ------------------------------------------------------------
    def find(self, query: str, type_filter: str = "", limit: int = 8,
             ttl: float = 30.0) -> dict:
        """Models that can do a described job, and what each would take.

        Two questions, kept apart on purpose. The score says how well a
        model fits the WORDS. The placement says what it would cost to
        RUN it - the NPU headroom beside what is already resident, and
        the disk left for the weights. A model that fits the words
        perfectly and cannot be placed is reported with that said
        plainly, rather than hidden.
        """
        now = time.monotonic()
        if FIND is None:
            return {"query": query, "error": "the find module is not available",
                    "terms": [], "hints": {}, "total": 0, "candidates": []}
        if (self._find_cache is not None
                and now - self._find_cache[0] < ttl
                and self._find_cache[1].get("query") == query
                and self._find_cache[1].get("type_filter") == type_filter):
            out = dict(self._find_cache[1])
            out["cached"] = True
            return out

        qterms = FIND.terms(query)
        hints = FIND.hints_for(query)

        rows = self.catalogue(full=True)
        storage = self.storage()

        by_target: dict[str, list[dict]] = {}
        for row in rows:
            by_target.setdefault(row["target"], []).append(row)

        incumbents = {tid: FIND.incumbent_npu(trows) for tid, trows in by_target.items()}

        # one entry per model, not per box: a model is a model, and which
        # box it would run on is a property of the placement.
        merged: dict[str, dict] = {}
        for row in rows:
            mid = row["model_id"]
            score, why = FIND.score_model(row, qterms, hints)
            entry = merged.get(mid)
            if entry is None:
                entry = {
                    "model_id": mid,
                    "name": row.get("name") or "",
                    "type": row.get("type") or "",
                    "capabilities": row.get("capabilities") or [],
                    "npu_usage": row.get("npu_usage"),
                    "context_window": row.get("context_window"),
                    "load_time": row.get("load_time"),
                    "recommend_rank": row.get("recommend_rank"),
                    "desc": (row.get("desc") or "")[:400],
                    "score": round(score, 2),
                    "why": why,
                }
                merged[mid] = entry
            elif score > entry["score"]:
                # the same model is described slightly differently on each
                # box; the best description wins
                entry["score"] = round(score, 2)
                entry["why"] = why

        for mid, entry in merged.items():
            placements = []
            for row in rows:
                if row["model_id"] != mid:
                    continue
                tid = row["target"]
                placements.append(FIND.placement(
                    self.by_id[tid], row, incumbents.get(tid, 0),
                    storage.get(tid), by_target.get(tid, [])))
            placements.sort(key=_placement_rank)
            entry["placements"] = placements
            entry["best_placement"] = placements[0] if placements else None

        candidates = [e for e in merged.values() if e["score"] > 0]
        candidates.sort(key=lambda e: (-e["score"], e["model_id"]))
        if type_filter:
            wanted = type_filter.lower()
            candidates = [e for e in candidates
                          if wanted in (e["type"] or "").lower()]
        candidates = candidates[:max(1, limit)]

        out = {
            "query": query,
            "terms": qterms,
            "hints": {k: v for k, v in hints.items()},
            "total": len(candidates),
            "candidates": candidates,
            "cached": False,
        }
        self._find_cache = (now, out)
        return out

    def _routable(self, target: "Target", row: dict) -> bool:
        """Can this target actually serve this model for this capability?

        A Tiiny serves only what is resident, but the mesh can load a
        downloaded model on demand - so a downloaded chat model is
        routable, just slower. A model that is not downloaded is not.

        A non-Tiiny target serves whatever its /v1/models lists, but only
        for the capabilities that target actually implements.
        """
        caps = row.get("capabilities") or []
        # the chat catalogue is for chat. An embedding model, an ASR model
        # or a reranker goes through its own endpoint, so publishing it
        # here is a lie a client will discover as a hard error.
        if not ("chat" in caps or "vision" in caps):
            return False
        if target.kind == "tiiny":
            # resident serves now; downloaded needs a load, which the
            # mesh can do - so both are routable
            return row.get("status") in ("running", "downloaded")
        return row.get("status") == "available"

    def chat_catalogue(self) -> list[dict]:
        """The models a chat client can actually use.

        `/v1/models` is the chat catalogue. Publishing an embedding model
        or an ASR model there is a lie: a client that picks one gets a
        hard error. The full catalogue, with every capability, is served
        separately at /mesh/catalogue.
        """
        return [r for r in self.catalogue() if r.get("routable")]

    def by_capability(self, capability: str) -> list[dict]:
        """Every model that can serve a capability, best target first."""
        rows = [r for r in self.catalogue()
                if capability in (r.get("capabilities") or [])]
        rows.sort(key=lambda r: (self.by_id[r["target"]].priority, r["target"]))
        return rows

    def available(self) -> list[dict]:
        """Only the models that could serve a request right now."""
        return self.chat_catalogue()

    def by_mesh_id(self, mesh_id: str) -> dict | None:
        for row in self.catalogue():
            if row["mesh_id"] == mesh_id:
                return row
        return None

    # -- routing ---------------------------------------------------------
    def resolve(self, model: str) -> tuple[Target | None, str, str]:
        """(target, upstream_model_id, how) for a requested model id.

        Three forms, in order of specificity:
          "target/model"  -> exactly that target
          "model"         -> the highest-priority target that serves it
          ""              -> the default target
        """
        if "/" in model and model.split("/", 1)[0] in self.by_id:
            tid, upstream = model.split("/", 1)
            return self.by_id[tid], upstream, "explicit"

        candidates = [r for r in self.available() if r["model_id"] == model]
        if not candidates:
            # maybe it is a mesh id without a live listing
            row = self.by_mesh_id(model)
            if row:
                return self.by_id[row["target"]], row["target_model_id"], "stale"
            return None, model, "unknown"

        # Residency beats non-residency to avoid unnecessary swaps;
        # then priority; then tie-break by target id.
        candidates.sort(key=lambda r: (
            0 if r.get("status") == "running" else 1,
            self.by_id[r["target"]].priority,
            r["target"],
        ))
        best = candidates[0]
        how = "resident" if best.get("status") == "running" else "priority"
        return self.by_id[best["target"]], best["target_model_id"], how

    def candidates_for(self, model: str) -> list[tuple[Target, str]]:
        """Every target that could serve this model, best first.

        Used for fallback: if the first target is unreachable, the same
        model on the next target is a better answer than an error.
        """
        if "/" in model and model.split("/", 1)[0] in self.by_id:
            tid, upstream = model.split("/", 1)
            return [(self.by_id[tid], upstream)]

        out = []
        for r in sorted((r for r in self.available() if r["model_id"] == model),
                        key=lambda r: self.by_id[r["target"]].priority):
            out.append((self.by_id[r["target"]], r["model_id"]))
        return out

    def borrow(self, target: Target, model: str) -> dict:
        """Load a model that is downloaded but not running, and note that we did.

        A Tiiny serves only what is resident. A model that is merely
        downloaded is not servable until it is loaded, and loading it can
        evict whatever was resident before.

        The NPU is shared and finite, so the caller must be able to put
        things back the way it found them. This returns what was resident
        beforehand so the caller can restore it.

        Returns {"needed": bool, "was_resident": [...], "ok": bool, ...}
        """
        if target.kind != "tiiny":
            return {"needed": False, "was_resident": [], "ok": True}
        state = catalogue(target)
        row = next((r for r in state["models"] if r["model_id"] == model), None)
        if row is None:
            return {"needed": False, "was_resident": [], "ok": False,
                    "error": f"{model} is not in this device's store"}
        if row.get("status") == "running":
            return {"needed": False, "was_resident": [], "ok": True}
        if row.get("status") != "downloaded":
            return {"needed": False, "was_resident": [], "ok": False,
                    "error": f"{model} is {row.get('status')}, not downloaded"}

        was = [r["model_id"] for r in state["models"] if r.get("status") == "running"]
        r = self.lifecycle(target.id, model, "start")
        ok = bool(r.get("ok"))
        if ok:
            status = self.wait_resident(target.id, model, wait_s=180)
            ok = status == "running"
        return {"needed": True, "was_resident": was, "ok": ok,
                "status": r.get("status"), "model": model, "target": target.id}

    def unborrow(self, target: Target, model: str, was_resident: list[str]) -> list[dict]:
        """Put the device back the way the borrow found it.

        Unloads the borrowed model, then re-loads anything that was
        resident before and did not survive the borrow.
        """
        if target.kind != "tiiny":
            return []
        out = []
        r = self.lifecycle(target.id, model, "stop")
        out.append({"target": target.id, "model": model, "action": "stop",
                    "ok": r.get("ok"), "http": r.get("status")})
        state = catalogue(target)
        running = {x["model_id"] for x in state["models"] if x.get("status") == "running"}
        for lost in was_resident:
            if lost in running or lost == model:
                continue
            r2 = self.lifecycle(target.id, lost, "start")
            out.append({"target": target.id, "model": lost, "action": "restore",
                        "ok": r2.get("ok"), "http": r2.get("status")})
        return out

    def call_with_borrow(self, target: Target, model: str, fn):
        """Call fn() against a target, borrowing the model if it needs one.

        A Tiiny serves only what is resident, so a TTS or ASR model that
        is merely downloaded has to be loaded first - and unloaded, and
        the previous resident set restored, afterwards. The endpoints that
        speak to an appliance all go through here so that rule cannot be
        forgotten in one of them.

        Returns (result, borrow_info). borrow_info is None when nothing
        was borrowed.
        """
        borrowed = None
        if target.kind == "tiiny" and model:
            b = self.borrow(target, model)
            if b.get("needed"):
                borrowed = b
                if not b.get("ok"):
                    return None, {"error": f"could not load {model} on {target.id}",
                                  "detail": b.get("error")}
        try:
            return fn(), ({"target": target.id, "model": model,
                           "was_resident": borrowed.get("was_resident", [])}
                          if borrowed else None)
        finally:
            if borrowed:
                self.unborrow(target, model, borrowed.get("was_resident", []))

    def chat(self, model: str, body: dict, timeout: int = 300,
             auto_load: bool = True) -> dict:
        """Route a chat request, with a retry and a fallback.

        Two failure modes are handled, because they are different problems:

          * a transient network error (the cloud target dropped the
            connection) - retried against the same target, because the
            request did not run
          * a target that cannot serve the request at all - fall back to
            the next target that has the same model, because the model
            exists elsewhere

        A 4xx is never retried. The caller asked for something wrong, and
        trying again would just waste the same error.

        With `auto_load`, a Tiiny target that has the model downloaded but
        not resident loads it for the request and puts the device back the
        way it found it afterwards.
        """
        want = model or ""
        tried: list[str] = []
        last: dict = {"ok": False, "error": "no target serves model " + repr(want)}
        borrow_info: dict = {}

        for target, upstream in self.candidates_for(want):
            tried.append(target.id)
            payload: dict = dict(body)
            payload["model"] = upstream
            for k, v in (target.extra_body or {}).items():
                payload.setdefault(k, v)

            # A Tiiny serves only what is resident. If the model is on the
            # box but not loaded, borrow it: load it, serve, then put the
            # device back the way it was found.
            borrowed = None
            if target.kind == "tiiny" and auto_load:
                b = self.borrow(target, upstream)
                if b.get("needed"):
                    borrowed = b
                    borrow_info = {"target": target.id, "model": upstream,
                                   "was_resident": b.get("was_resident", [])}
                    if not b.get("ok"):
                        last = {"ok": False, "error": f"could not load {upstream} on {target.id}",
                                "detail": b.get("error"), "target": target.id}
                        continue

            try:
                for attempt in range(2):
                    status, resp, _ = _request(
                        target.base_url.rstrip("/") + "/chat/completions",
                        target.key(), method="POST", body=payload, timeout=timeout)
                    if status is not None:
                        if 200 <= status < 300 and isinstance(resp, dict):
                            # A thinking model that runs out of budget returns
                            # empty content and a full reasoning channel.
                            # `chat_template_kwargs` silences the Qwen family
                            # but not gpt-oss, which always reasons - so give
                            # it room once rather than returning nothing.
                            if _thinking_starved(resp) and int(
                                    payload.get("max_tokens") or 0) < THINKING_BUDGET:
                                payload["max_tokens"] = THINKING_BUDGET
                                status, resp, _ = _request(
                                    target.base_url.rstrip("/") + "/chat/completions",
                                    target.key(), method="POST", body=payload, timeout=timeout)
                            if not isinstance(resp, dict):
                                resp = {"error": "target returned a non-JSON body",
                                        "raw": str(resp)[:400]}
                            resp.setdefault("mesh_target", target.id)
                            resp["mesh_route"] = {
                                "target": target.id, "requested": want,
                                "served": upstream,
                                "how": "explicit" if want.startswith(target.id + "/") else "priority",
                                "tried": tried,
                                "borrowed": bool(borrowed),
                            }
                            return {"ok": True, "status": status, "payload": resp,
                                    "target": target.id, "attempts": attempt + 1,
                                    "borrowed": borrow_info}
                        if status == 429:
                            last = {"ok": False, "status": status, "payload": resp,
                                    "target": target.id, "attempts": attempt + 1,
                                    "borrowed": borrow_info,
                                    "error": f"target {target.id} returned HTTP 429 rate limit"}
                            # Check for configured cloud fallback
                            sec_entry = (self.policy.get("chat") or {}).get("secondary")
                            if sec_entry:
                                sec_target, sec_upstream = self._resolve_entry(sec_entry, "chat")
                                if sec_target and sec_target.id not in tried:
                                    sys.stderr.write(
                                        f"[mesh:failover] {target.id} returned HTTP 429 -> failing over to {sec_entry}\\n")
                                    fb_res = self.chat(sec_entry, body, timeout=timeout, auto_load=auto_load)
                                    if fb_res.get("ok"):
                                        if isinstance(fb_res.get("payload"), dict) and "mesh_route" in fb_res["payload"]:
                                            fb_res["payload"]["mesh_route"]["failover_from"] = target.id
                                            fb_res["payload"]["mesh_route"]["failover_reason"] = "429 rate limit"
                                        return fb_res
                            break

                        # a real answer from the target: pass it through, even
                        # if it is an error the caller needs to see
                        return {"ok": False, "status": status, "payload": resp,
                                "target": target.id, "attempts": attempt + 1,
                                "borrowed": borrow_info,
                                "error": f"target {target.id} returned HTTP {status}"}
                    # status is None: a transport failure. Retry once, then
                    # move to the next target.
                    last = {"ok": False, "error": f"target {target.id} unreachable",
                            "detail": str(resp)[:300], "target": target.id}
                    if attempt == 0:
                        time.sleep(1.5)
            finally:
                if borrowed:
                    restored = self.unborrow(target, upstream, borrowed.get("was_resident", []))
                    borrow_info = dict(borrow_info)
                    borrow_info["restored"] = restored

        return last

    def default_target(self) -> Target | None:
        if not self.targets:
            return None
        return sorted(self.targets, key=lambda t: t.priority)[0]

    # -- lifecycle (Tiiny only) -----------------------------------------
    def boot_target(self, target_id: str) -> dict:
        """Start a stopped local server, using the target's `boot` command.

        A target with a `boot` command - a stopped LM Studio server, say -
        can be brought up on demand. Without one, a down target stays
        down: there is nothing to run.

        The command is whatever the config says, so it is the operator's
        call, not the mesh's.
        """
        t = self.by_id.get(target_id)
        if t is None:
            return {"ok": False, "error": f"no target {target_id}"}
        if not t.boot:
            return {"ok": False, "error": f"{target_id} has no boot command"}
        import subprocess
        try:
            r = subprocess.run(t.boot, capture_output=True, text=True, timeout=120)
        except Exception as e:
            return {"ok": False, "error": f"boot failed: {type(e).__name__}: {e}"}
        return {"ok": r.returncode == 0, "target": target_id,
                "command": t.boot, "returncode": r.returncode,
                "output": (r.stdout or r.stderr or "")[-400:]}

    def restore(self, wait_s: int = 90) -> list[dict]:
        """Re-load the models a target is supposed to keep resident.

        A Tiiny unloads everything on reboot, so after the appliances come
        back the routes 404 until a model is loaded. This is the unattended
        restore path: check what is running, load what should be, and
        report what happened.

        Only targets that declare `keep_resident` take part. The Octo
        deliberately does not - its loads are supervised work, and
        auto-loading there would fight the person watching it.
        """
        results = []
        for t in self.targets:
            if t.kind != "tiiny" or not t.keep_resident:
                continue
            state = catalogue(t)
            running = {r["model_id"] for r in state["models"]
                       if r.get("status") == "running"}
            for model in t.keep_resident:
                if model in running:
                    results.append({"target": t.id, "model": model,
                                    "action": "already resident"})
                    continue
                r = self.lifecycle(t.id, model, "start")
                results.append({"target": t.id, "model": model,
                                "action": "start", "ok": r.get("ok"),
                                "http": r.get("status")})
        return results

    def wait_resident(self, target_id: str, model: str, wait_s: int = 90) -> str:
        """Poll the device until a model is resident. Returns its status."""
        t = self.by_id.get(target_id)
        if t is None:
            return "unknown target"
        deadline = time.time() + wait_s
        status = "unknown"
        while time.time() < deadline:
            state = catalogue(t)
            for r in state["models"]:
                if r["model_id"] == model:
                    status = r.get("status") or "unknown"
                    if status == "running":
                        return status
            time.sleep(4)
        return status

    def lifecycle(self, target_id: str, model: str, action: str) -> dict:
        """download | start | stop on a Tiiny, over the device's own HTTP API."""
        t = self.by_id.get(target_id)
        if t is None:
            return {"ok": False, "error": f"no target {target_id}"}
        if t.kind != "tiiny":
            return {"ok": False, "error": f"{target_id} is not an appliance; it has no model lifecycle"}
        status, payload, _ = _request(
            t.admin(f"/api/v1/models/{model}/{action}"), t.key(), method="POST", body={})
        return {"ok": status is not None and 200 <= status < 300,
                "status": status, "target": target_id, "model": model,
                "action": action, "detail": payload if not isinstance(payload, dict) else payload}


    # -- pools (capacity-aware) ------------------------------------------
    def pools(self) -> dict:
        """NPU capacity for every Tiiny target, never summed into one.

        Each Tiiny in the estate is its own pool: a client that knows the
        NPU footprint of a model can pick the right appliance without a
        central aggregator.  The mesh never collapses these into a single
        pool because that hides where the memory actually lives.
        """
        pools_list = []
        for target in self.targets:
            if target.kind != "tiiny":
                continue
            st_npu, npu_payload, _ = _request(
                target.admin("/api/v1/npu/status"), target.key(), timeout=10)
            st_mod, mod_payload, _ = _request(
                target.admin("/api/v1/models/running"), target.key(), timeout=10)
            mem_used_mb = 0.0
            mem_total_mb = 0.0
            if isinstance(npu_payload, dict):
                devices = npu_payload.get("devices") or []
                for dev in devices:
                    if not isinstance(dev, dict):
                        continue
                    mem_used_mb += dev.get("mem_used_mb") or 0.0
                    mem_total_mb += dev.get("mem_total_mb") or 0.0
            if not mem_total_mb:
                mem_total_mb = 49024.0
            if not mem_used_mb and isinstance(npu_payload, dict):
                for dev in npu_payload.get("devices") or []:
                    if isinstance(dev, dict):
                        mem_used_mb += dev.get("mem_used_mb") or 0.0
            mem_free_mb = max(0.0, mem_total_mb - mem_used_mb)
            util_percent = round((mem_used_mb / mem_total_mb) * 100.0, 1) if mem_total_mb else 0.0
            resident_models = []
            if isinstance(mod_payload, dict):
                resident_models = mod_payload.get("running") or mod_payload.get("models") or mod_payload.get("model_ids") or []
            elif isinstance(mod_payload, list):
                resident_models = [m for m in mod_payload if isinstance(m, str)]
            status_npu = st_npu if st_npu is not None else None
            pools_list.append({
                "target": target.id,
                "name": target.id,
                "address": target.admin_url.split("//", 1)[-1].split(":")[0] if target.admin_url else "",
                "npu_status": npu_payload.get("npu", {}).get("status", "unknown") if isinstance(npu_payload, dict) else "unknown",
                "mem_used_mb": round(mem_used_mb, 1),
                "mem_total_mb": round(mem_total_mb, 1),
                "mem_free_mb": round(mem_free_mb, 1),
                "util_percent": util_percent,
                "resident_models": resident_models,
                "ok": status_npu == 200,
            })
        return {"ok": True, "pools": pools_list}


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------


def health(target: Target) -> dict:
    """Can this target answer right now, and how fast."""
    t0 = time.time()
    status, payload, _ = _request(target.models_url(), target.key(), timeout=8)
    ms = int((time.time() - t0) * 1000)
    ok = status == 200
    models = 0
    if ok:
        if isinstance(payload, dict):
            items = payload.get("data") or payload.get("models") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        models = len(items)
    return {"target": target.id, "kind": target.kind, "ok": ok, "http": status,
            "ms": ms, "models": models, "url": target.base_url}
