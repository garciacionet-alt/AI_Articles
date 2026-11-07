"""The contracts. A requirement vector is what the LLM produces; a resolution
is what the deterministic resolver produces from it."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, PositiveInt


class Artifact(str, Enum):
    ICON = "icon"
    ILLUSTRATION = "illustration"
    PHOTO = "photo"
    LOGO = "logo"
    POSTER = "poster"
    INFOGRAPHIC = "infographic"
    COMIC = "comic"
    CHARACTER_SHEET = "character_sheet"
    TEXTURE = "texture"
    CUTOUT = "cutout"
    EDIT = "edit"
    STICKER = "sticker"

    @classmethod
    def _missing_(cls, value: object) -> "Artifact | None":
        """Accept an artifact the registry does not declare.

        The registry's taxonomy is the source of truth for what the appliance
        can do, but a user may ask for anything. An unknown artifact must
        still resolve — the resolver's soft artifact filter falls back to the
        whole catalogue — rather than fail validation at the boundary.
        """
        if isinstance(value, str):
            member = str.__new__(cls, value)
            member._name_ = value.upper().replace("-", "_").replace(" ", "_")
            member._value_ = value
            return member
        return None


class EditOp(str, Enum):
    NONE = "none"
    BACKGROUND_REMOVE = "background_remove"
    OBJECT_REMOVE = "object_remove"
    OUTPAINT = "outpaint"
    DETAIL_REGEN = "detail_regen"


class RequirementVector(BaseModel):
    """What the user actually needs, extracted from their words."""

    artifact: Artifact = Artifact.ILLUSTRATION
    alpha: Literal["required", "preferred", "no"] = "no"
    text_in_image: Literal["required", "preferred", "no"] = "no"
    style: str = "general"
    edit_op: EditOp = EditOp.NONE
    width: PositiveInt = 1024
    height: PositiveInt = 1024
    speed: Literal["fastest", "normal", "quality_first"] = "normal"
    hard: list[str] = Field(default_factory=list)


class ModelChoice(BaseModel):
    id: str
    role: str
    npu_usage: int
    co_resident_with_planner: bool
    combined_npu_pct: int
    #: Is the model on the appliance's disk? A model that is not
    #: downloaded cannot be loaded, so it can be offered as an
    #: alternative — "download this and it would work" — but never
    #: chosen.
    downloaded: bool = True


class Resolution(BaseModel):
    """The resolver's answer, with the reasoning attached."""

    chosen: ModelChoice
    requirements: RequirementVector
    justification: str
    alternatives: list[ModelChoice] = Field(default_factory=list)
    #: Models that would satisfy the request but are NOT downloaded on
    #: the appliance, so they cannot be loaded. "Download this and it
    #: becomes possible" is more useful than a bare refusal.
    unavailable: list[ModelChoice] = Field(default_factory=list)
    swap_required: bool = False
    swap_plan: dict[str, list[str]] = Field(default_factory=dict)
    generation_occupancy_pct: int = 0
    planner_resident: bool = False
    exceeds_measured_ceiling: bool = False
    reasons: list[str] = Field(default_factory=list)
