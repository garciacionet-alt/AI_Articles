# Feeding .docx Files to Your OpenHuman Agent

**By Gary Garcia and Agent 99 · August 11, 2026 · v1.0**

**Problem:** The OpenHuman UI has no method for uploading a `.docx` file directly to your agent. Users end up converting to PDF and relying on OCR, which wastes tokens and loses formatting.

**Solution:** OpenHuman's agent workspace *is a folder on disk*. Drop a `.docx` into that folder, and your agent can read and edit it natively — no PDF, no OCR, formatting preserved.

## The Mental Model

OpenHuman agents read files from their workspace, which is a real folder on your machine. Anything you put there is something your agent can open. The `docx` skill simply removes the PDF/OCR fallback for Word documents — the agent reads the `.docx` directly.

## Setup (one-time)

### 1. Link the projects folder to your desktop (recommended)

OpenHuman's UI lives on your desktop — that's where you work. The fastest way to get files into your agent is to make the projects folder appear right there, so you can drag files in without keeping Finder open.

Create a symlink (or Finder alias) from your desktop to the OpenHuman projects folder:

On macOS, in Terminal:

```bash
ln -s "<path to your OpenHuman projects folder>" ~/Desktop/OpenHuman-Projects
```

> **Where is the projects folder?** It's the agent's workspace root. On this setup it lives under iCloud Drive (e.g. `~/Library/Mobile Documents/com~apple~CloudDocs/OpenHuman/projects/`). Confirm the exact path by asking your agent for its working directory.

### 2. Install the docx skill

Install the `docx` skill from the skill registry (it's the Nous Research / built-in one). Your agent can do this for you, or you can install it yourself.

## The Workflow

1. **Drop** the `.docx` you want to work with onto the desktop symlink (or into the projects folder directly).
2. **Tell your agent** to find and edit it, e.g. "Open `Gary-AMD.August11.docx` in the job search folder and change X to Y."
3. **The agent** finds the file in its workspace, reads it natively, makes the edit, and saves in place.
4. **You get back** the same `.docx` with formatting intact — bold, italic, styles, tables all preserved.

## What Works

- **Native reading** — no PDF conversion, no OCR, far fewer tokens.
- **Formatting preserved** — bold, italic, and styles survive edits.
- **In-place editing** — the agent edits the file directly; no re-upload needed.
- **Repeatable** — a helper CLI (`docx_edit.py`) supports read / replace / append for scripted or batch edits.

## Troubleshooting

- **"I can't find the file"** — the file must be inside the agent's workspace folder, not just anywhere on disk. The desktop symlink resolves to that folder, so dropping on the symlink works — but a file sitting loose on the desktop (outside the symlink) does not.
- **Path restrictions** — agents can't read arbitrary paths outside their workspace (e.g. `~/.openhuman/...`). Always drop files into the workspace folder.
- **Formatting looks off** — if an edit spans multiple runs of text, the agent may apply the formatting of the first run it touches. For complex edits, ask the agent to verify formatting after saving.

## Disclaimer

This solution has been tested by one person on a Mac running OpenHuman, using the built-in `docx` skill and a `python-docx` helper. The concept has not been tested on Windows or Linux, though it should work there in principle.

This solution has **not** been tested by the OpenHuman team and is **not supported by them**. The file-handling and skill systems in OpenHuman have changed more than once in recent months, so the ability to self-support this solution matters.

**No warranty is offered or implied.** This is a workflow, not a product. If you read this and don't understand how it works, do not attempt it. Edits are made in place to your original file, so if you don't understand how your environment differs, back up your documents first.

## Why This Matters

This pattern isn't just about `.docx` — it's the general trick for getting any file into your agent's hands when the UI won't let you upload it. Drop it in the workspace, reference it by name, and let the agent's native file tools do the rest.

*Feeding .docx Files to Your OpenHuman Agent · v1.0 · August 11, 2026 · Gary Garcia and Agent 99*

---

## Enabling the Subconscious Loop (config.toml)

The OpenHuman UI toggle for the subconscious loop doesn't always persist. If you flip it on, restart, and the loop still isn't running, edit the config file directly.

**File to edit:**
`/Users/gary/.openhuman/users/6a1a5cb31adafc7a08afdedb/config.toml`

(Confirm your exact path by asking your agent for its data directory. This guide is written against schema_version 6.)

**The real gates** are the `local_ai` runtime flags and the `*_provider` fields. The legacy `[local_ai.usage]` booleans are preset/migration-only and do NOT override the provider fields after migration.

**Edits (current value → new value):**

In the `[local_ai]` section — turn the local runtime on:
```toml
runtime_enabled = false   →   runtime_enabled = true
opt_in_confirmed = false  →   opt_in_confirmed = true
```

Fix the subconscious provider — it must point at a CHAT model, not an embedding model:
```toml
subconscious_provider = "ollama:bge-m3"   →   subconscious_provider = "ollama:gemma3:1b-it-qat"
```
(`bge-m3` is an embedding model. The subconscious loop is a chat/reasoning workload, so it needs a chat model like `gemma3:1b-it-qat`.)

In the `[heartbeat]` section — enable the tick loop (there is no `subconscious_mode` key in this schema; the heartbeat block is what fires ticks):
```toml
enabled = false              →   enabled = true
inference_enabled = false    →   inference_enabled = true
```

**Optional — route embeddings and the memory tree fully local** (only if you want on-device, not cloud):
```toml
[memory]
embedding_provider = "cloud"   →   embedding_provider = "ollama"
embedding_model = "embedding-v1"   →   embedding_model = "bge-m3"

[memory_tree]
llm_backend = "cloud"   →   llm_backend = "local"
```

**After editing:** save the file, then fully quit and relaunch OpenHuman (not just a window close — the daemon needs to re-read config on boot).

**Also check:** the models must be pulled in Ollama: `gemma3:1b-it-qat` (chat) and `bge-m3` (embeddings), or the loop won't have a model to run on.

**Verify:** after restart, check **Intelligence → Subconscious** in the UI (or `openhuman.inference_status` via CLI) to confirm the loop is enabled and ticking.

---
