# Two Tiiny Boxes, One System — Implementation

The concrete setup: two appliances, one client, and the order to do it in.
Read [PATTERN.md](./PATTERN.md) for why each step is shaped the way it is.

## Prerequisites

- Two Tiiny appliances, on the same LAN, each with its own address.
- The device control CLI (`tiiny`), installed and working for the first box.
- A client that talks to an OpenAI-compatible endpoint, and a controller
  that can load models onto a device.
- Both boxes signed in to the desktop application. **The application
  session is the gate on the device's API** — with no session, the routes
  refuse even a valid credential.

## Step 1 — declare the boxes

One section per box, in a small file:

```ini
# ~/.config/hermes/tiiny-boxes.conf
[vault]
host    = 192.0.2.50
key_env = TIINY_API_KEY

[flex]
host     = 192.0.2.51
key_env  = TIINY_API_KEY_2
own_lock = yes
```

- `host` — the box's own address. Give it a DHCP reservation first.
- `key_env` — the name of the credential in the client's environment file.
- `own_lock` — `yes` gives that box its own lock, hold, plan and catalogue
  snapshot. **Leave it off for the box whose default paths the scheduled
  jobs already use.** Two agents sharing one pool must share one lock; the
  second box is a different pool and gets its own.

## Step 2 — onboard the second box

```bash
bash scripts/onboard_tiiny_box.sh --device 192.0.2.51 --key-env TIINY_API_KEY_2
```

What it does, in order:

1. backs up the control CLI's configuration and points it at the box;
2. runs the CLI's login for **that address** (interactive — you type your
   email code);
3. fetches the box's credential, captured without printing it;
4. writes it into the client's environment file with mode 0600;
5. restores the CLI configuration to the box it was on;
6. verifies the box's store, its served models, and one real completion.

The credential never appears on screen, in shell history, or in any file
other than the environment file. The script exits non-zero if the login did
not complete, and the configuration is restored either way.

Doing it by hand, if you prefer:

```bash
tiiny login --device-address 192.0.2.51
tiiny auth key --device-address 192.0.2.51     # copy the credential
# append to the environment file, mode 0600:
#   TIINY_API_KEY_2=<credential>
```

Then point the CLI back at the first box (`tiiny connect <first-box-ip>`)
so the next load lands in the right place.

## Step 3 — point the client at each box

One provider per box, each with its own endpoint and its own credential:

```yaml
providers:
  tiiny:
    name: tiiny
    api: http://192.0.2.50/v1
    key_env: TIINY_API_KEY
    transport: chat_completions
    default_model: Qwen/Qwen3.6-35B-A3B
    context_length: 262144
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  tiiny2:
    name: tiiny2
    api: http://192.0.2.51/v1
    key_env: TIINY_API_KEY_2
    transport: chat_completions
    default_model: Qwen/Qwen3.6-35B-A3B
    context_length: 262144
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
```

**Restart the client afterwards.** The provider block and the environment
file are both read at startup, and a stale endpoint reads as a client
that works and bills you for the wrong thing.

## Step 4 — split the roles

On the **vault** box, keep resident the models that must always be there:

```bash
python3 scripts/tiiny_ctl.py ensure --model "Qwen/Qwen3.6-35B-A3B"
```

On the **flex** box, let the router load what the batch needs:

```bash
python3 scripts/tiiny_ctl.py ensure --model "Qwen/Qwen3.8-27B"
```

Run them per box with the wrapper, which sets the endpoint, the credential
and the state paths from the boxes file:

```bash
bash scripts/tiiny_box.sh vault status
bash scripts/tiiny_box.sh flex  status
bash scripts/tiiny_box.sh flex  ensure --model "Qwen/Qwen3.8-27B"
```

## Verifying the split

```bash
# both boxes reachable, each with its own credential and its own state
bash scripts/tiiny_box.sh vault status
bash scripts/tiiny_box.sh flex  status

# the catalogues really are the same
for ip in 192.0.2.50 192.0.2.51; do
  curl -s -H "Authorization: Bearer $KEY" "http://$ip/api/v1/models/online_models" \
    | python3 -c "import sys,json;print(len(json.load(sys.stdin)))"
done

# and each answers a completion on its own
curl -s -X POST http://192.0.2.51/v1/chat/completions \
  -H "Authorization: Bearer $TIINY_API_KEY_2" -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3.6-35B-A3B","messages":[{"role":"user","content":"Reply with exactly: OK"}],
       "max_tokens":64,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}'
```

Two boxes answering at once is the whole point. If one of them returns 401
while the other serves, that is a credential problem, not a capacity
problem.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 401 on a box that is powered on | The credential belongs to the other box | Fetch this box's credential with its own address |
| "Not logged in" from the CLI | The session is bound to another address | Log in again, addressed at this box |
| A load reports success but the model is absent | The CLI session was not authenticated | Check the CLI session; the exit code is non-zero, so trust it |
| The client answers with the wrong box's models | It is pointed at the vendor hostname | Address the boxes directly |
| Two agents evict each other | One lock file for two pools | One lock per pool; `own_lock = yes` for the second box |
| A catalogue diff reports vanished models | One snapshot file for two devices | One snapshot per device |
| The box looks empty | A storage endpoint, not a presence measure | Read each model's `status` in the catalogue |
| A renamed box is not found | The name is a label | Key everything on the device id |
| The client works but costs money it should not | The provider was pinned to an address that moved | Reserve the address in the router |
| The client bills for a model it did not use | The model was never resident; the request fell back | Make the load verdict unambiguous and check it |

## Maintenance

- **Reserve both addresses.** This is the one task that prevents a silent
  bill.
- **Release, do not leave loaded.** After a batch, restore the box's
  required set so the next child finds its model.
- **Refresh each box's catalogue separately.** One snapshot per device, or
  a refresh on one replaces the other's baseline.
- **Re-read the catalogue when the firmware moves.** Model stores change
  with every update; the tier table is a snapshot, not a constant.
- **Keep the vendor hostname out of client configuration.** It follows the
  desktop application's selection and answers for one box at a time.
