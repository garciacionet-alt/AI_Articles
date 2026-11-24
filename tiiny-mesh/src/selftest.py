#!/usr/bin/env python3
"""Exercise TiinyMesh against the live targets.

This is the real test: every target is a machine on this LAN or a cloud
endpoint, and a mesh that cannot see them is a mesh in a file.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh as M  # noqa: E402

# the env file the shell would normally have loaded
env = Path.home() / ".hermes" / ".env"
if env.exists():
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

print("=== 1. health of every target ===")
m = M.Mesh.load(os.environ.get("TIINY_MESH_CONFIG", M.DEFAULT_CONFIG))
for t in m.targets:
    h = M.health(t)
    mark = "ok " if h["ok"] else "DOWN"
    print(f"  {mark} {h['target']:12s} HTTP {h['http']}  {h['ms']:>4}ms  models={h['models']}")
    if not h["ok"]:
        print(f"       ({t.note})")

print("\n=== 2. the merged catalogue ===")
rows = m.catalogue()
by_target = {}
for r in rows:
    by_target.setdefault(r["target"], []).append(r)
for target, trows in by_target.items():
    live = [r for r in trows if r.get("status") in ("running", "available", "downloaded")]
    print(f"  {target:12s} {len(trows):>3} models  ({len(live)} reachable now)")
    for r in trows[:3]:
        extra = ""
        if r.get("npu_usage") is not None:
            extra = f"  npu={r['npu_usage']}%  ctx={r.get('context_window')}"
        print(f"      {r['model_id'][:52]:52s} {r.get('status','')}{extra}")
    if len(trows) > 3:
        print(f"      ... and {len(trows) - 3} more")

print("\n=== 3. routing a model id ===")
for want in ("Qwen/Qwen3.6-35B-A3B",
             "tiiny-octo/Qwen/Qwen3.6-35B-A3B",
             "tiiny-octo/deepreinforce-ai/Ornith-1.0-35B",
             "bge-m3:latest",
             "gemma3:4b",
             "minimax/MiniMax-M3",
             "Qwen/Qwen3.8-27B"):
    target, upstream, how = m.resolve(want)
    label = target.id if target else "(none)"
    print(f"  {want[:44]:44s} -> {label:12s} as {upstream[:32]:32s} ({how})")

print("\n=== 4. a real completion through the mesh ===")
target, upstream, how = m.resolve("Qwen/Qwen3.6-35B-A3B")
if target:
    body = {"model": upstream,
            "messages": [{"role": "user", "content": "Reply with exactly: MESH-OK"}],
            "max_tokens": 32, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    status, payload, _ = M._request(target.base_url.rstrip("/") + "/chat/completions",
                                    target.key(), method="POST", body=body, timeout=90)
    text = ""
    if isinstance(payload, dict):
        try:
            text = payload["choices"][0]["message"]["content"]
        except Exception:
            text = json.dumps(payload)[:120]
    print(f"  target={target.id} upstream={upstream} HTTP {status} -> {text!r}")

print("\n=== 5. lifecycle on a Tiiny (the thing the CLI could not do) ===")
r = m.lifecycle("tiiny-octo", "Qwen/Qwen3.8-27B", "start")
print(f"  start Qwen/Qwen3.8-27B on tiiny-octo -> ok={r['ok']} http={r.get('status')}")
if r["ok"]:
    import time
    row = None
    for _ in range(20):
        time.sleep(3)
        row = m.by_mesh_id("tiiny-octo/Qwen/Qwen3.8-27B")
        if row and row.get("status") == "running":
            print("  -> resident")
            break
    else:
        print(f"  -> status is {(row or {}).get('status', 'unknown')}")
    r2 = m.lifecycle("tiiny-octo", "Qwen/Qwen3.8-27B", "stop")
    print(f"  stop -> ok={r2['ok']} http={r2.get('status')}")
else:
    print(f"  detail: {str(r.get('detail'))[:200]}")
