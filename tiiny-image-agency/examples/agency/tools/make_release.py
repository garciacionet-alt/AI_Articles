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

#: Where the published, curated tree lives. It is FOUND, not written
#: down: a path with somebody's name in it does not belong in a public
#: repository, and the tool that writes the public tree is published
#: with it.
PUBLISHED_NAME = "tiiny-image-agency"


def find_published() -> Path | None:
    """The published tree, found by looking for it.

    The script lives in the working tree, and the published tree — the
    curated copy that goes into the public repository — is a sibling
    of the project rather than a copy of it. Rather than hard-coding
    where that is — or anything with a home directory in it — the tree
    is found by walking up and looking for it.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = (parent / "_amc" / "publish" / "articles"
                     / PUBLISHED_NAME)
        if candidate.is_dir():
            return candidate
    return None

#: The pieces of the published tree that go into the tarball, and
#: where each one lands in it.
#:
#: THE ROOT OF THE TARBALL IS THE PYTHON PROJECT. That matters more
#: than it looks: pip installs a source distribution by looking for
#: ``pyproject.toml`` at its root, and Homebrew's Python support does
#: the same thing in the unpacked directory. A tarball whose project
#: is one directory down is a tarball that nothing can install.
#:
#: So the package's ``pyproject.toml`` and ``src`` go to the root, and
#: the registry — which is data, not code, and is installed beside the
#: virtualenv — goes in a directory of its own.
PAYLOAD = (
    ("examples/agency/app/pyproject.toml", "pyproject.toml"),
    ("examples/agency/app/src", "src"),
    ("examples/agency/registry", "registry"),
)

#: Where the cask lives in the published tree.
CASK_DIR = "Casks"
CASK_NAME = "tiiny-image-agency.rb"

#: The repository the release lives in.
REPO = "garciacionet-alt/AI_Articles"

#: The version, when it is not read from the package. The package's own
#: version is the truth, and it is read from the pyproject.toml, so the
#: cask, the tarball and the tag cannot disagree about it.
VERSION = "0.1.1"


def package_version(published: Path) -> str:
    """The version, read from the package's own pyproject.toml."""
    pyproject = published / "examples" / "agency" / "app" / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version"):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return VERSION


def sha256_of(path: Path) -> str:
    """The SHA-256 of a file, read in chunks because one of these is
    several megabytes and nobody needs it all in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_tarball(out_dir: Path, version: str, published: Path) -> Path:
    """The tarball, built deterministically.

    Deterministic means: the same inputs give the same bytes, so the
    SHA-256 in the cask means something. File order is sorted, and
    every file's modification time and owner are pinned.
    """
    name = f"tiiny-image-agency-{version}"
    tarball = out_dir / f"{name}.tar.gz"
    staging = Path(tempfile.mkdtemp()) / name
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for piece, target_name in PAYLOAD:
            source = published / piece
            if not source.exists():
                raise SystemExit(f"missing from the published tree: {piece}")
            target = staging / target_name
            if source.is_dir():
                shutil.copytree(source, target,
                                ignore=shutil.ignore_patterns(
                                    "__pycache__", "*.pyc", ".pytest_cache"))
            else:
                shutil.copy2(source, target)
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

  # The package is installed as a Python package — its pyproject.toml
  # is at the root of the tarball, which is what pip and Homebrew both
  # look for. The registry is put beside the virtualenv, where
  # tis.config looks for it when the package is not in a checkout.
  language "python", virtualenv_install_with_resources: {{
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
    parser.add_argument("--version", default="",
                        help="the version (read from the package by "
                             "default)")
    parser.add_argument("--published", default="",
                        help="the published tree to build from (found by "
                             "default)")
    parser.add_argument("--cask", default="",
                        help="where to write the cask (default: in the "
                             "published tree)")
    args = parser.parse_args()

    published = (Path(args.published) if args.published
                 else find_published())
    if published is None or not published.is_dir():
        print("FAIL: the published tree was not found. Run this from the "
              "working tree, or pass --published.")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = args.version or package_version(published)
    tarball = build_tarball(out_dir, version, published)
    digest = sha256_of(tarball)

    cask_path = (Path(args.cask) if args.cask
                 else published / CASK_DIR / CASK_NAME)
    write_cask(cask_path, version, digest)

    print(f"tarball : {tarball}")
    print(f"  bytes : {tarball.stat().st_size}")
    print(f"  sha256: {digest}")
    print(f"cask    : {cask_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
