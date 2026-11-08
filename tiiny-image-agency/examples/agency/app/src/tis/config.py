"""Paths and runtime settings. The bearer is read here and nowhere else."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "http://openai.api.tiiny"
INFERENCE_SUFFIX = "/v1"

#: Where an INSTALL puts the data that travels with the package. The
#: cask installs it beside the virtualenv, and this is the name it
#: uses.
SHARE_NAME = "tiiny-image-agency"


def _checkout_root() -> Path:
    """The project root of a SOURCE CHECKOUT.

    The package is at app/src/tis there, so the root is three levels
    up. In an install the package is in site-packages and three levels
    up is the virtualenv — which is why this is a separate function and
    why the caller checks it before trusting it.
    """
    return Path(__file__).resolve().parents[3]


def _get_project_root() -> Path:
    """Where the agency's data lives.

    The data is found by LOOKING FOR IT, not by counting directories,
    because the two ways this package is used put it in different
    places:

    1. a source checkout, recognised by its registry;
    2. an install, recognised by the data the cask put beside the
       virtualenv — ``<prefix>/share/tiiny-image-agency``;
    3. and if neither is there, the user's own directory. A missing
       directory is a bad default, and a directory the user can find is
       at least writable.
    """
    checkout = _checkout_root()
    if (checkout / "registry" / "image-models.json").is_file():
        return checkout
    installed = Path(sys.prefix) / "share" / SHARE_NAME
    if (installed / "registry" / "image-models.json").is_file():
        return installed
    return Path.home() / f".{SHARE_NAME}"


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    #: The CONVERSATION AGENT - the model that turns a request into a
    #: requirement vector.
    #:
    #: It was a 55% Coder, and it was NOT ON THE APPLIANCE. Every plan
    #: was therefore failing and falling back to the keyword planner, so
    #: the style words a request used were being thrown away - "anime"
    #: became "general", because no curated model declares that style,
    #: and the fallback only knows the catalogue's vocabulary.
    #:
    #: The default is now the 27% chat model the watchdog already holds.
    #: It is resident, so planning costs no swap at all, and it writes a
    #: better vector than the bigger model did - it put "anime" into the
    #: modifiers where the image model can see it.
    planner_model: str = "openai/gpt-oss-20b"
    planner_npu_pct: int = 27
    #: The CRITIC - the model that judges the result. It is a SEPARATE
    #: setting because a critic that can SEE the image is a different
    #: model from the one that wrote the prompt, and because the two
    #: roles have different residency needs: the judge has to fit
    #: beside the generator or it never runs.
    #:
    #: It MUST be a vision model. A critic that cannot see the image
    #: judges the prompt, and a prompt judge does not fail loudly - it
    #: invents a defect, and every invented defect costs a generation.
    #: So the rule is enforced here, in the guide and in the choice, and
    #: a text-only model is refused rather than quietly accepted.
    judge_model: str = "Qwen/Qwen3.6-35B-A3B"
    #: Where the conversational catalogue lives - the models that can
    #: hold either role.
    roles_path: Path = field(
        default_factory=lambda: Path(os.environ.get("TIIS_ROLES_PATH", _get_project_root() / "registry" / "roles.json")).expanduser()
    )
    registry_path: Path = field(
        default_factory=lambda: Path(os.environ.get("TIIS_REGISTRY_PATH", _get_project_root() / "registry" / "image-models.json")).expanduser()
    )
    assets_dir: Path = field(default_factory=lambda: Path(os.environ.get("TIIS_ASSETS_DIR", _get_project_root() / "assets")).expanduser())
    #: Where the saved references live. A reference is a result the user
    #: liked and wants more like, so it is kept with its recipe.
    references_dir: Path = field(default_factory=lambda: Path(os.environ.get("TIIS_REFERENCES_DIR", _get_project_root() / "references")).expanduser())
    #: Where the research cards live. The research loop writes them.
    cards_dir: Path = field(default_factory=lambda: Path(os.environ.get("TIIS_CARDS_DIR", _get_project_root() / "research")).expanduser())
    hold_file: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.hermes/tiiny-hold")))
    watchdog_lock: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.hermes/tiiny-watch.lock")))
    tiiny_bin: Path = field(default_factory=lambda: Path(os.path.expanduser("~/.local/tiiny/bin/tiiny")))

    @property
    def inference_base(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith(INFERENCE_SUFFIX):
            return base
        return base + INFERENCE_SUFFIX


def load_settings() -> Settings:
    """Build settings from the environment. Never raises on a missing key —
    the adapter reports the auth failure at call time, not at import time."""
    key = os.environ.get("TIINY_API_KEY", "")
    return Settings(api_key=key)