"""The `tis` command line interface: the agency from a terminal.

The CLI is an HTTP CLIENT of the public API, not a second in-process
Agency, and that is the whole design:

  The API server OWNS the appliance. There is exactly one process holding
  the NPU and the hold file. A CLI that drove the device itself would
  contend with a running server over the hold file, which is global to
  the device - and two processes both believing they own the appliance
  is the exact failure the cross-agent lock exists to prevent.

So the CLI needs no credential of its own, and must not ask for one. The
bearer stays on the appliance side, where it belongs.

Two things it has to get right, because a person is watching:

  A generation takes 54 to 200 SECONDS. A command that hangs with no
  output is indistinguishable from a broken one, so every event is
  printed as it arrives.

  The exit code is what a script reads. It is 0 only when the thing
  actually happened.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx

#: What the CLI says when it cannot reach the agency. The point is that
#: the reader is told WHAT TO DO, not that something went wrong.
NOT_RUNNING = "the agency is not running; start it with 'tis serve'"

DEFAULT_BASE_URL = "http://127.0.0.1:8080"


@dataclass
class Target:
    """Where the agency is."""

    base_url: str

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


# -- the commands --------------------------------------------------------


def serve(host: str, port: int) -> int:
    """Run the API locally, so the CLI has something to talk to.

    The server owns the appliance. Until it is running, every other
    command has nothing to talk to - which is why the error message
    says so.
    """
    import uvicorn

    from .api import create_app

    app = create_app()
    print(f"The agency is serving on http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)
    return 0


def models(args: argparse.Namespace, target: Target) -> int:
    """List the image models the appliance can make."""
    try:
        data = _get(target, "/v1/models")
    except httpx.RequestError:
        return _not_running()

    if args.json:
        print(json.dumps(data))
        return 0

    print(f"{'ID':<44} {'ROLE':<16} {'NPU%':<6} {'ALPHA':<6} {'TEXT':<10} ARTIFACTS")
    for model in data.get("models", []):
        print(f"{model.get('id', ''):<44} {model.get('role', ''):<16} "
              f"{model.get('npu_usage', ''):<6} "
              f"{('yes' if model.get('alpha') else 'no'):<6} "
              f"{model.get('text_rendering', ''):<10} "
              f"{', '.join(model.get('artifacts') or [])}")
    return 0


def npu(args: argparse.Namespace, target: Target) -> int:
    """Show what is resident on the appliance right now."""
    try:
        data = _get(target, "/v1/npu")
    except httpx.RequestError:
        return _not_running()

    if args.json:
        print(json.dumps(data))
        return 0

    if not data.get("reachable", True):
        print("The appliance is not reachable.")
        return 1
    print(f"NPU used: {data.get('used_pct', 0)}%")
    print(f"Resident: {', '.join(data.get('resident') or []) or '(none)'}")
    return 0


def health(args: argparse.Namespace, target: Target) -> int:
    """Is the agency alive, and is the appliance reachable?"""
    try:
        data = _get(target, "/v1/health")
    except httpx.RequestError:
        return _not_running()

    if args.json:
        print(json.dumps(data))
        return 0

    print(f"agency    : {'alive' if data.get('alive') else 'not alive'}")
    print(f"appliance : {'reachable' if data.get('device_reachable') else 'NOT reachable'}")
    print(f"registry  : {data.get('model_count', 0)} models")
    # A reachable appliance is what makes the agency useful, so an
    # unreachable one is a failure even though the app is alive.
    return 0 if data.get("device_reachable") else 1


def plan(args: argparse.Namespace, target: Target) -> int:
    """Plan a request: which model, at what cost, and why.

    Costs nothing but a planner call, and the justification is the
    resolver explaining itself - which is the interesting part of the
    product.
    """
    try:
        data = _post(target, "/v1/plan", {"request": args.prompt})
    except httpx.RequestError:
        return _not_running()

    if args.json:
        print(json.dumps(data))
        return 0

    model = data.get("model") or {}
    print(f"Model          : {model.get('id')}")
    print(f"NPU            : {model.get('npu_usage')}%")
    print(f"Swap required  : {data.get('swap_required')}")
    print(f"Planned by     : {data.get('planner_source')}")
    print(f"Justification  :\n{data.get('justification', '')}")
    alternatives = data.get("alternatives") or []
    if alternatives:
        print("Alternatives:")
        for alternative in alternatives:
            print(f"  - {alternative.get('id')} ({alternative.get('npu_usage')}% NPU)")
    return 0


def generate(args: argparse.Namespace, target: Target) -> int:
    """Make an image, watch it happen, and save it."""
    body = {"request": args.prompt}
    if getattr(args, "model", None):
        # A model the user chose. The agency honours it when it can do
        # the job, and says so when it cannot.
        body["model_id"] = args.model
    if getattr(args, "reference", None):
        # A saved result to come out like. Its model and its
        # requirements are used, so the same job comes out the same way
        # twice.
        body["reference_id"] = args.reference
    try:
        data = _post(target, "/v1/generate", body)
    except httpx.RequestError:
        return _not_running()

    session_id = data.get("session_id")
    job_id = data.get("job_id")
    if not session_id or not job_id:
        print("Error: the agency did not return a job", file=sys.stderr)
        return 1
    return _follow(target, session_id, job_id, args.out)


def iterate(args: argparse.Namespace, target: Target) -> int:
    """Revise an existing image with the user's feedback."""
    try:
        data = _post(target, "/v1/iterate",
                     {"asset_id": args.asset_id, "feedback": args.prompt})
    except httpx.RequestError:
        return _not_running()

    session_id = data.get("session_id")
    job_id = data.get("job_id")
    if not session_id or not job_id:
        print("Error: the agency did not return a job", file=sys.stderr)
        return 1
    return _follow(target, session_id, job_id, args.out)


def pdf(args: argparse.Namespace, target: Target) -> int:
    """Make a PDF of some assets, one page each.

    The newsletter case: the images the agency made, in one file to
    send. The images go into the PDF as they are — a JPEG as JPEG, an
    RGB PNG's compressed scanlines as they are, and an RGBA PNG's alpha
    as its own transparency channel — because a PDF page is opaque and
    an image that arrives flattened has lost something the agency
    promised to keep.

        tis pdf ast_0123456789abcdef ast_fedcba9876543210 --out news.pdf
    """
    body = {
        "asset_ids": list(args.asset_ids),
        "output_path": args.out or "",
    }
    if args.title:
        body["title"] = args.title
    try:
        data = _post(target, "/v1/documents", body)
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except ValueError:
            detail = exc.response.text[:200]
        print(f"Error: {detail or 'the document was refused'}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{data.get('path')}")
    print(f"  {data.get('pages')} page(s), {data.get('bytes')} bytes")
    return 0


def reference(args: argparse.Namespace, target: Target) -> int:
    """Save a result as a reference, list them, or forget one.

    A reference is a result the user liked, kept with the RECIPE that
    made it - the model, the dialect, the size, the requirements. Using
    one means: make the new subject in that style. That is how a
    repeated job stays a repeated job.

        tis reference save ast_0123456789abcdef --name "newsletter"
        tis reference list
        tis reference forget ref_0123456789abcdef
    """
    try:
        if args.reference_command == "save":
            body = {"asset_id": args.asset_id}
            if args.name:
                body["name"] = args.name
            data = _post(target, "/v1/references", body)
            print(f"{data.get('id')}  {data.get('name')}")
            print(f"  made with {data.get('model_id')}  "
                  f"{data.get('size')}")
            return 0

        if args.reference_command == "forget":
            response = httpx.delete(f"{target.url}/v1/references/"
                                    f"{args.reference_id}", timeout=60)
            response.raise_for_status()
            print(f"forgot {args.reference_id}")
            return 0

        data = _get(target, "/v1/references")
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = exc.response.text[:200]
        print(f"Error: {detail or exc.response.status_code}", file=sys.stderr)
        return 1
    except httpx.RequestError:
        return _not_running()

    references = data.get("references") or []
    if not references:
        print("No references yet. Save one with:")
        print("  tis reference save <asset_id> --name \"...\"")
        return 0
    for entry in references:
        bits = [entry.get("id", ""), entry.get("name", "")]
        if entry.get("model_id"):
            bits.append(entry.get("model_id"))
        if entry.get("size"):
            bits.append(entry.get("size"))
        print("  " + "  ".join(str(bit) for bit in bits if bit))
    return 0


def roles(args: argparse.Namespace, target: Target) -> int:
    """Show - or choose - the models that talk and judge.

    The GUIDE: every conversational model the appliance offers, whether
    or not it can SEE an image, what each costs, and whether it is on
    the device right now.

    The CHOICE: `tis roles --critic <model>` sets the judge. A judge
    that can see the image judges the PICTURE; one that cannot judges
    only the prompt.
    """
    body = {}
    if args.conversation:
        body["conversation"] = args.conversation
    if args.critic:
        body["critic"] = args.critic
    try:
        if body:
            data = _post(target, "/v1/roles", body)
        else:
            data = _get(target, "/v1/roles")
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = exc.response.text[:200]
        print(f"Error: {detail or exc.response.status_code}", file=sys.stderr)
        return 1
    except httpx.RequestError:
        return _not_running()

    if args.json:
        print(json.dumps(data))
        return 0

    conversation = data.get("conversation") or {}
    critic = data.get("critic") or {}
    print("WHO TALKS")
    print(f"  {conversation.get('model', '—')}  "
          f"({conversation.get('npu_usage', 0)}% NPU)")
    print()
    print("WHO JUDGES")
    sees = "CAN SEE the image" if critic.get("vision") else "text only — judges the PROMPT"
    print(f"  {critic.get('model', '—')}  ({critic.get('npu_usage', 0)}% NPU)  "
          f"{sees}")
    if data.get("note"):
        print(f"  {data['note']}")
    fit = data.get("fit") or {}
    if fit:
        mark = "fits" if fit.get("fits") else "DOES NOT FIT"
        # The talker is not in this sum. It has already written the scene
        # description by the time the image is made, so its weights are
        # swapped out and it does not compete for the pool.
        print(f"  While judging: {fit.get('critic_npu', 0)}% judging + "
              f"{fit.get('generator_npu', 0)}% generating = "
              f"{fit.get('total', 0)}% of the pool — {mark}")
    print()
    print("THE MODELS THAT CAN SEE AN IMAGE")
    print(f"  {'MODEL':<46} {'NPU':>4}  {'ON DEVICE':<12} NOTES")
    for model in data.get("vision_models", []):
        mark = "yes" if model.get("downloaded") else "not yet"
        note = (model.get("notes") or "").strip().splitlines()
        first = note[0] if note else ""
        print(f"  {model['id']:<46} {model.get('npu_usage', 0):>4}%  "
              f"{mark:<12} {first}")
    return 0


def alpha(args: argparse.Namespace) -> int:
    """Measure a PNG's transparency.

    "Does this model render a transparent background" is the one fact a
    vision model cannot answer: a transparent image composited onto a
    viewer's background looks opaque. So it is measured, from the pixels.

    This READS the file and never writes it. A PNG that came out of the
    agency must not be re-encoded, resized or re-saved - that is exactly
    where a transparent background quietly becomes an opaque one.
    """
    from .imaging import PngError, alpha_stats, read_info

    path = Path(args.image)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"Error: could not read {path}: {exc}", file=sys.stderr)
        return 1
    try:
        info = read_info(data)
    except PngError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    stats = alpha_stats(data)
    if args.json:
        print(json.dumps({"image": info.to_dict(),
                          "alpha": stats.to_dict()}))
        return 0

    print(f"{info.width}x{info.height} {info.colour_type_name}"
          + ("" if info.has_alpha_channel else " — no alpha channel"))
    print(f"fully transparent  : {stats.transparent_pct}%")
    print(f"partly transparent : {stats.partial_pct}%")
    print(f"fully opaque       : {stats.fully_opaque_px}/{stats.total_px} pixels")
    if stats.unreadable:
        print(f"note               : {stats.unreadable}")
    return 0


# -- the shared machinery ------------------------------------------------


def _get(target: Target, path: str) -> dict:
    response = httpx.get(target.url(path), timeout=30.0)
    response.raise_for_status()
    return response.json()


def _post(target: Target, path: str, payload: dict) -> dict:
    response = httpx.post(target.url(path), json=payload, timeout=30.0)
    response.raise_for_status()
    return response.json()


def _not_running() -> int:
    print(f"Error: {NOT_RUNNING}", file=sys.stderr)
    return 1


def _follow(target: Target, session_id: str, job_id: str,
            out: Optional[str]) -> int:
    """Follow the event stream, then fetch and save the asset.

    The bus REPLAYS a session's recent events to a late subscriber, so
    it does not matter that the job was posted before the stream was
    opened: the events in between are not lost.

    It matters a great deal that the replay brings events from EARLIER
    jobs in the same session. Those are printed — they are part of the
    session's story — but they must never DECIDE anything. A second
    generation in the same session used to pick up the first job's
    `asset.ready` and save the first image under the second job's name,
    in under a second, without generating anything at all.

    So: everything is shown, and only this job's events count. An event
    with no job id — the swap events — is not ours to act on.
    """
    asset_id: Optional[str] = None
    url = target.url(f"/v1/session/{session_id}/events?job_id={job_id}")
    try:
        with httpx.stream("GET", url, timeout=None) as stream:
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    payload = json.loads(line[len("data: "):].strip())
                except json.JSONDecodeError:
                    continue
                kind = payload.get("type")
                data = payload.get("data") or {}
                _print_event(payload)

                if data.get("job_id") != job_id:
                    continue

                if kind == "asset.ready":
                    asset_id = data.get("asset_id")
                elif kind == "job.finished":
                    asset_id = asset_id or data.get("asset_id")
                    break
                elif kind == "job.failed":
                    print(f"Error: {data.get('error', 'the job failed')}",
                          file=sys.stderr)
                    return 1
    except httpx.RequestError:
        return _not_running()

    if not asset_id:
        print("Error: the job finished without producing an asset",
              file=sys.stderr)
        return 1
    return _save(target, asset_id, out)


def _print_event(payload: dict) -> None:
    """One event, on one line, with a clock a person can read."""
    stamp = payload.get("ts")
    when = ""
    if isinstance(stamp, (int, float)):
        when = time.strftime("%H:%M:%S", time.localtime(stamp))
    kind = payload.get("type", "")
    data = payload.get("data") or {}
    detail = data.get("model") or data.get("asset_id") or data.get("job_id") or ""
    print(f"[{when}] {kind:<18} {detail}", flush=True)


def _save(target: Target, asset_id: str, out: Optional[str]) -> int:
    """Fetch the PNG and write it out EXACTLY as the appliance made it.

    The bytes are not decoded, re-encoded or re-saved. A round trip
    through an image library is precisely where a transparent background
    quietly becomes an opaque one, and the alpha channel is the reason
    the flagship model is worth its 62% of the NPU.
    """
    try:
        response = httpx.get(target.url(f"/v1/assets/{asset_id}"), timeout=60.0)
        response.raise_for_status()
    except httpx.RequestError:
        return _not_running()

    path = Path(out) if out else Path(f"{asset_id}.png")
    path.write_bytes(response.content)
    print(f"Asset written to {path}")
    return 0


# -- the entry point -----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """The parser, with the common options accepted BEFORE or AFTER the
    command.

    `tis models --json` and `tis --json models` are both natural to type,
    and argparse will not do both on its own: the subparser's default
    would overwrite the main parser's value. SUPPRESS on the shared
    options is the fix - a subparser that did not see the flag leaves
    the attribute alone.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default=argparse.SUPPRESS,
                        help="Base URL of the agency (default: $TIS_URL, "
                             f"or {DEFAULT_BASE_URL})")
    common.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS,
                        help="Print one JSON object instead of text")

    parser = argparse.ArgumentParser(
        prog="tis",
        description="Tiiny Image Agency - plan and generate images on the "
                    "local Tiiny appliance.",
    )
    # The MAIN parser defines the options with real defaults. The shared
    # parent is for the SUBCOMMANDS only: it is the same option declared
    # twice, and argparse refuses an option string that appears twice on
    # one parser.
    parser.add_argument("--url", default=os.getenv("TIS_URL", DEFAULT_BASE_URL),
                        help="Base URL of the agency")
    parser.add_argument("--json", action="store_true", default=False,
                        help="Print one JSON object instead of text")

    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser(
        "serve", parents=[common], help="Run the agency locally")
    serve_parser.add_argument("--host", default="127.0.0.1",
                              help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8080,
                              help="Port to bind to")

    subparsers.add_parser("models", parents=[common],
                           help="List the image models")
    subparsers.add_parser("npu", parents=[common],
                           help="Show what is resident right now")
    subparsers.add_parser("health", parents=[common],
                           help="Is the agency alive")

    alpha_parser = subparsers.add_parser(
        "alpha", parents=[common],
        help="Measure a PNG's transparency")
    alpha_parser.add_argument("image", help="the PNG to measure")

    roles_parser = subparsers.add_parser(
        "roles", parents=[common],
        help="Show or choose the models that talk and judge")
    roles_parser.add_argument(
        "--critic", default=None,
        help="the model that judges the result (one that can SEE the image "
             "judges the picture, not just the prompt)")
    roles_parser.add_argument(
        "--conversation", default=None,
        help="the model that turns a request into a requirement vector")

    plan_parser = subparsers.add_parser(
        "plan", parents=[common], help="Plan a request without generating")
    plan_parser.add_argument("prompt", help="What you want, in words")

    generate_parser = subparsers.add_parser(
        "generate", parents=[common], help="Generate an image")
    generate_parser.add_argument("prompt", help="What you want, in words")
    generate_parser.add_argument("--out", default=None,
                                 help="Where to write the PNG")
    generate_parser.add_argument(
        "--model", default=None,
        help="the model to use, instead of the one the resolver picks. "
             "Honoured when it can do the job; the agency says so when "
             "it cannot. Run 'tis plan' to see the alternatives.")
    generate_parser.add_argument(
        "--reference", default=None,
        help="a saved reference to come out like. Its model and its "
             "requirements are used, so the same job comes out the same "
             "way twice. Run 'tis reference list' to see them.")

    iterate_parser = subparsers.add_parser(
        "iterate", parents=[common], help="Revise an existing image")
    iterate_parser.add_argument("asset_id", help="The asset to revise")
    iterate_parser.add_argument("prompt", help="What to change")
    iterate_parser.add_argument("--out", default=None,
                                help="Where to write the PNG")

    pdf_parser = subparsers.add_parser(
        "pdf", parents=[common],
        help="Make a PDF of some assets, one page each")
    pdf_parser.add_argument(
        "asset_ids", nargs="+",
        help="The assets, in the order they should appear")
    pdf_parser.add_argument("--out", default=None,
                             help="Where to write the PDF")
    pdf_parser.add_argument(
        "--title", default="",
        help="A title for the document's metadata. It is not drawn on "
             "the page — a PDF title needs a font, and a font is a "
             "dependency.")

    reference_parser = subparsers.add_parser(
        "reference", parents=[common],
        help="Save, list or forget a reference")
    reference_sub = reference_parser.add_subparsers(
        dest="reference_command", required=True)
    reference_save = reference_sub.add_parser(
        "save", help="Save a delivered image as a reference")
    reference_save.add_argument("asset_id", help="The asset to keep")
    reference_save.add_argument("--name", default="",
                                help="A name, so you can find it again")
    reference_sub.add_parser("list", help="The saved references")
    reference_forget = reference_sub.add_parser(
        "forget", help="Forget a reference")
    reference_forget.add_argument("reference_id", help="The reference to forget")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run one command. The return value is the exit code."""
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    target = Target(args.url)
    try:
        if args.command == "serve":
            return serve(args.host, args.port)
        if args.command == "models":
            return models(args, target)
        if args.command == "npu":
            return npu(args, target)
        if args.command == "health":
            return health(args, target)
        if args.command == "alpha":
            return alpha(args)
        if args.command == "roles":
            return roles(args, target)
        if args.command == "plan":
            return plan(args, target)
        if args.command == "generate":
            return generate(args, target)
        if args.command == "iterate":
            return iterate(args, target)
        if args.command == "pdf":
            return pdf(args, target)
        if args.command == "reference":
            return reference(args, target)
        raise ValueError(f"unknown command: {args.command}")
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except Exception:
            detail = exc.response.text[:200]
        print(f"Error: the agency answered {exc.response.status_code}"
              f"{': ' + detail if detail else ''}", file=sys.stderr)
        return 1
    except httpx.RequestError:
        return _not_running()
    except Exception as exc:  # noqa: BLE001 - a CLI must not traceback
        print(f"Error: {exc}", file=sys.stderr)
        return 1


#: So that `python -m tis.cli` works as well as the installed `tis`
#: script. Without this the module loads, defines everything, and exits
#: without doing anything - which looks exactly like a silent success.
if __name__ == "__main__":
    raise SystemExit(main())
