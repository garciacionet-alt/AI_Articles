import pytest
from pydantic import ValidationError

from tis.models import RequirementVector, ModelChoice, Resolution, Artifact, EditOp


def test_requirement_vector_defaults():
    """A RequirementVector with no arguments gets the documented defaults."""
    req = RequirementVector()
    assert req.artifact == Artifact.ILLUSTRATION
    assert req.alpha == "no"
    assert req.text_in_image == "no"
    assert req.style == "general"
    assert req.edit_op == EditOp.NONE
    assert req.width == 1024
    assert req.height == 1024
    assert req.speed == "normal"
    assert req.hard == []


def test_requirement_vector_hard_list_is_not_shared():
    """hard is NOT a shared mutable default."""
    req1 = RequirementVector()
    req2 = RequirementVector()
    req1.hard.append("test")
    assert req2.hard == []


def test_requirement_vector_invalid_alpha():
    """RequirementVector rejects an invalid alpha value."""
    with pytest.raises(ValidationError):
        RequirementVector(alpha="maybe")


def test_requirement_vector_invalid_speed():
    """RequirementVector rejects an invalid speed value."""
    with pytest.raises(ValidationError):
        RequirementVector(speed="quick")


def test_requirement_vector_invalid_dimensions():
    """RequirementVector rejects a non-positive width or height."""
    with pytest.raises(ValidationError):
        RequirementVector(width=0)
    with pytest.raises(ValidationError):
        RequirementVector(height=0)
    with pytest.raises(ValidationError):
        RequirementVector(width=-100)
    with pytest.raises(ValidationError):
        RequirementVector(height=-100)


def test_requirement_vector_artifact_round_trip():
    """artifact="icon" round-trips."""
    req = RequirementVector(artifact=Artifact.ICON)
    assert req.artifact == Artifact.ICON


def test_resolution_minimal_fields():
    """A Resolution built with only the three required fields gets default values."""
    choice = ModelChoice(
        id="test_id",
        role="test_role",
        npu_usage=10,
        co_resident_with_planner=True,
        combined_npu_pct=50
    )
    req = RequirementVector()
    res = Resolution(
        chosen=choice,
        requirements=req,
        justification="test justification"
    )
    assert res.alternatives == []
    assert res.swap_required is False
    assert res.swap_plan == {}
    assert res.generation_occupancy_pct == 0


def test_resolution_occupancy_field_defaults():
    """The occupancy fields default to 'not co-resident, within the ceiling'."""
    res = Resolution(
        chosen=ModelChoice(
            id="test_id",
            role="test_role",
            npu_usage=10,
            co_resident_with_planner=True,
            combined_npu_pct=50
        ),
        requirements=RequirementVector(),
        justification="test justification"
    )
    assert res.planner_resident is False
    assert res.exceeds_measured_ceiling is False
    assert res.reasons == []


def test_resolution_reasons_is_not_shared():
    """reasons is NOT a shared mutable default."""
    def make() -> Resolution:
        return Resolution(
            chosen=ModelChoice(
                id="test_id",
                role="test_role",
                npu_usage=10,
                co_resident_with_planner=True,
                combined_npu_pct=50
            ),
            requirements=RequirementVector(),
            justification="test justification"
        )

    res1 = make()
    res2 = make()
    res1.reasons.append("alpha required")
    assert res2.reasons == []


def test_model_choice_round_trip():
    """A ModelChoice round-trips through .model_dump() and back."""
    original = ModelChoice(
        id="test_id",
        role="test_role",
        npu_usage=10,
        co_resident_with_planner=True,
        combined_npu_pct=50
    )
    dumped = original.model_dump()
    recreated = ModelChoice(**dumped)
    assert recreated.id == original.id
    assert recreated.role == original.role
    assert recreated.npu_usage == original.npu_usage
    assert recreated.co_resident_with_planner == original.co_resident_with_planner
    assert recreated.combined_npu_pct == original.combined_npu_pct


def test_artifact_accepts_a_value_the_registry_does_not_declare():
    """The registry's taxonomy is the source of truth, but a user may ask for
    anything. An unknown artifact must still construct rather than fail
    validation at the boundary — the resolver's soft artifact filter falls
    back to the whole catalogue."""
    vector = RequirementVector(artifact="blueprint")
    assert vector.artifact.value == "blueprint"
    assert vector.artifact == "blueprint"

    dumped = vector.model_dump()
    assert RequirementVector(**dumped).artifact.value == "blueprint"


def test_artifact_still_rejects_a_non_string():
    """Only strings can name an artifact."""
    with pytest.raises(Exception):
        RequirementVector(artifact=42)