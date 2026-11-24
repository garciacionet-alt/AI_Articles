#!/usr/bin/env python3
"""OpenRouter target kind — offline, no network."""
import os
import sys
import json
import tempfile
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mesh as M

def t(name, fn):
    try:
        fn()
        print("  ok   ", name)
        return 0
    except AssertionError as e:
        print("  FAIL ", name, "-", e)
        return 1

fails = 0

def config_accepts_kind():
    doc = {"targets": {"or": {
        "kind": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "models": ["openai/gpt-4o"],
        "priority": 70,
        "capabilities": ["chat"],
    }}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(doc, fh)
        path = fh.name
    m = M.Mesh.load(path)
    os.unlink(path)
    assert len(m.targets) == 1, m.targets
    tg = m.targets[0]
    assert tg.kind == "openrouter", tg.kind
    assert tg.models_url() == "https://openrouter.ai/api/v1/models", tg.models_url()
    assert tg.chat_url() == "https://openrouter.ai/api/v1/chat/completions", tg.chat_url()

def openrouter_classified():
    import capabilities as CAP
    caps = CAP.classify_generic("openai/gpt-4o")
    assert "chat" in caps, caps

def openrouter_chat_capable():
    import capabilities as CAP
    assert CAP.is_chat_capable(CAP.classify_generic("anthropic/claude-3.5-sonnet"))

def openrouter_resolution():
    doc = {"targets": {"openrouter": {
        "kind": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet"],
        "priority": 70,
        "capabilities": ["chat"],
    }}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(doc, fh)
        path = fh.name
    m = M.Mesh.load(path)
    os.unlink(path)
    target, upstream, how = m.resolve("openrouter/openai/gpt-4o")
    assert target is not None, "Target should resolve"
    assert target.id == "openrouter", target.id
    assert upstream == "openai/gpt-4o", upstream
    assert how == "explicit", how

    # Also test catalogue namespacing and routable
    cat = m.catalogue()
    mesh_ids = [r["mesh_id"] for r in cat]
    assert "openrouter/openai/gpt-4o" in mesh_ids, mesh_ids
    chat_cat = m.chat_catalogue()
    chat_mesh_ids = [r["mesh_id"] for r in chat_cat]
    assert "openrouter/openai/gpt-4o" in chat_mesh_ids, chat_mesh_ids

fails += t("config accepts openrouter kind", config_accepts_kind)
fails += t("openrouter classified as chat", openrouter_classified)
fails += t("openrouter chat capable", openrouter_chat_capable)
fails += t("openrouter resolution & catalogue", openrouter_resolution)
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
