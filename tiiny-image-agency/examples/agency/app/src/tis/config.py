"""Paths and runtime settings. The bearer is read here and nowhere else."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "http://openai.api.tiiny"
INFERENCE_SUFFIX = "/v1"


def _get_project_root() -> Path:
    """Return the project root path.

    The package is at app/src/tis, so the project root is three levels up.
    This path can be overridden via environment variables.
    """
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    #: The CONVERSATION AGENT - the model that turns a request into a
    #: requirement vector. It is also the default critic, because until
    #: the critic can see the image there was nothing to distinguish it.
    planner_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct-Turbo"
    planner_npu_pct: int = 55
    #: The CRITIC - the model that judges the result. It is a SEPARATE
    #: setting because a critic that can SEE the image is a different
    #: model from the one that wrote the prompt, and because the two
    #: roles have different residency needs: the judge has to fit
    #: beside the generator or it never runs.
    #:
    #: Empty means "the same model as the conversation agent".
    judge_model: str = ""
    #: Where the conversational catalogue lives - the models that can
    #: hold either role.
    roles_path: Path = field(
        default_factory=lambda: Path(os.environ.get("TIIS_ROLES_PATH", _get_project_root() / "registry" / "roles.json")).expanduser()
    )
    registry_path: Path = field(
        default_factory=lambda: Path(os.environ.get("TIIS_REGISTRY_PATH", _get_project_root() / "registry" / "image-models.json")).expanduser()
    )
    assets_dir: Path = field(default_factory=lambda: Path(os.environ.get("TIIS_ASSETS_DIR", _get_project_root() / "assets")).expanduser())
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