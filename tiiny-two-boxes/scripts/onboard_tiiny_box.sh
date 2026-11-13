#!/usr/bin/env bash
# onboard_tiiny_box.sh — open a second Tiiny appliance for a client.
#
# WHY THIS EXISTS
# ---------------
# Each appliance has its OWN device-admin credential, issued by
# `tiiny auth key --device-address <ip>`. The CLI will only issue a box's
# credential to a session bound to that box's address, so signing in to the
# desktop application is not enough - the CLI needs its own login for the
# address. `tiiny login` is interactive, so it is a human step; everything
# after it is mechanical, and this script does all of it.
#
# WHAT IT DOES
#   1. backs up the CLI configuration and points it at the box
#   2. runs `tiiny login` for that box (interactive: you type your code)
#   3. fetches that box's credential, captured WITHOUT printing it
#   4. writes it into the client's environment file, mode 0600
#   5. restores the CLI configuration to the box it was on
#   6. verifies the box's store, its served models and one real completion
#
# The credential never appears on screen, in the shell history, or in any
# file other than the environment file.
#
# Usage
#   onboard_tiiny_box.sh --device <ip> --key-env <NAME> [--name <label>]
#   onboard_tiiny_box.sh --device <ip> --key-env <NAME> --dry-run
#   onboard_tiiny_box.sh --device <ip> --key-env <NAME> --no-login
set -uo pipefail

TIINY_CLI="${TIINY_BIN:-$HOME/.local/tiiny/bin/tiiny}"
CLI_CFG="${TIINY_CLI_CONFIG:-$HOME/.local/tiiny/config.json}"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"

DEVICE=""
KEY_ENV=""
LABEL=""
DRY_RUN=0
DO_LOGIN=1

while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --key-env) KEY_ENV="$2"; shift 2 ;;
    --name) LABEL="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --no-login) DO_LOGIN=0; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "onboard_tiiny_box: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$DEVICE" ] || [ -z "$KEY_ENV" ]; then
  echo "onboard_tiiny_box: --device and --key-env are both required" >&2
  echo "  e.g. --device 192.0.2.51 --key-env TIINY_API_KEY_2" >&2
  exit 2
fi
if [ ! -x "$TIINY_CLI" ]; then
  echo "onboard_tiiny_box: the tiiny CLI is missing at $TIINY_CLI" >&2
  exit 2
fi
if [ ! -f "$CLI_CFG" ]; then
  echo "onboard_tiiny_box: no CLI config at $CLI_CFG" >&2
  exit 2
fi

umask 077
BACKUP="$(mktemp -t tiinycfg.XXXXXX)"
CAPTURE="$(mktemp -t tiinykey.XXXXXX)"
chmod 600 "$BACKUP" "$CAPTURE"
cp "$CLI_CFG" "$BACKUP"
ORIG_DEVICE="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('deviceAddress',''))" "$CLI_CFG")"

restore() {
  cp "$BACKUP" "$CLI_CFG" 2>/dev/null
  rm -f "$BACKUP" "$CAPTURE"
}
trap restore EXIT INT TERM

echo "onboard_tiiny_box"
echo "  box     : $DEVICE ${LABEL:+($LABEL)}"
echo "  key name: $KEY_ENV"
echo "  cli cfg : $CLI_CFG (device was $ORIG_DEVICE)"
echo

# 1. point the CLI at this box
python3 -c "
import json, sys
p, dev = sys.argv[1], sys.argv[2]
d = json.load(open(p)); d['deviceAddress'] = dev
json.dump(d, open(p, 'w'), indent=1)
" "$CLI_CFG" "$DEVICE"

# 2. log in, if asked and if needed
if [ "$DO_LOGIN" -eq 1 ]; then
  echo "-> signing the CLI in for $DEVICE (interactive: enter your email code)"
  # the CLI opens /dev/tty for interactive prompts, so it needs a pty
  script -q /dev/null "$TIINY_CLI" login --device-address "$DEVICE"
  LOGIN_RC=$?
  if [ "$LOGIN_RC" -ne 0 ]; then
    echo "  login did not complete (exit $LOGIN_RC) - stopping" >&2
    exit 1
  fi
  echo
fi

# 3. fetch the credential, captured and never printed
echo "-> fetching the box's API credential"
"$TIINY_CLI" auth key --device-address "$DEVICE" > "$CAPTURE" 2>/dev/null
KEY="$(sed -n 's/.*API Credentials:[[:space:]]*\([^[:space:]]*\).*/\1/p' "$CAPTURE" | head -1)"
if [ -z "$KEY" ]; then
  echo "  no credential returned - the CLI is not signed in for $DEVICE." >&2
  echo "  run it again and complete the login." >&2
  exit 1
fi
echo "  got a credential (length ${#KEY}, value withheld)"

# 4. store it
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  dry run: NOT writing to $HERMES_ENV"
else
  python3 -c "
import os, stat, sys
env, name, key = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(env).read().splitlines()
out, done = [], False
for ln in lines:
    if ln.startswith(name + '='):
        out.append(name + '=' + key); done = True
    else:
        out.append(ln)
if not done:
    out.append(name + '=' + key)
open(env, 'w').write('\n'.join(out) + '\n')
os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)
print('  written to %s as %s (0600)' % (env, name))
" "$HERMES_ENV" "$KEY_ENV" "$KEY"
  rm -f "$CAPTURE"
  echo "  the temporary capture was deleted"
fi

# 5. verify the box really opens
echo
echo "-> verifying $DEVICE"
python3 - "$DEVICE" "$KEY" <<'PYEOF'
import json, sys, urllib.request, urllib.error
ip, key = sys.argv[1], sys.argv[2]


def get(path):
    r = urllib.request.Request(f"http://{ip}{path}", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:120]
    except Exception as e:
        return 0, str(e)[:120]


code, body = get("/api/v1/models/online_models")
if code == 200:
    print(f"  store        : HTTP 200, {len(json.loads(body))} models")
else:
    print(f"  store        : HTTP {code} {body[:80]}")
code, body = get("/v1/models")
ids = []
if code == 200:
    ids = [m.get("id") for m in json.loads(body).get("data", [])]
    print(f"  served models: {ids or '(none loaded)'}")
else:
    print(f"  served models: HTTP {code} {body[:80]}")

if ids:
    payload = json.dumps({
        "model": ids[0],
        "messages": [{"role": "user", "content": "Reply with exactly: BOX-OK"}],
        "max_tokens": 64, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    r = urllib.request.Request(f"http://{ip}/v1/chat/completions", data=payload,
                               headers={"Authorization": f"Bearer {key}",
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            d = json.loads(resp.read().decode())
            print(f"  completion   : {d['choices'][0]['message'].get('content')!r} "
                  f"({d['usage']['completion_tokens']} tokens)")
    except Exception as e:
        print(f"  completion   : failed - {e}")
else:
    print("  completion   : skipped (no model loaded on this box)")
PYEOF

echo
echo "The CLI configuration is restored to $ORIG_DEVICE on exit."
echo "Add the box to your boxes file, then point a provider at it."
